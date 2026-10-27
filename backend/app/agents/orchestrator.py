"""Orchestrator — relays requests, coordinates the Coaches, reconciles daily plans (UC09) and drives the UC10 loop.

It never rewrites a Coach's content and never decides whether something is released:
that is the Safety Supervisor's job. Every user-facing personalised candidate goes through
``run_review_pipeline``.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from ..db import models as m
from ..domain.enums import (AgentRole, AllergyStatus, CandidateKind, CandidateStatus, ConflictType, ConsentScope, DecisionType,
                            IntegrationState, NotificationKind, OutcomeStatus, ProfileStatus, RequestState)
from ..domain.schemas import (ActivityFeedbackIn, AdaptRequestIn, DailyPlanRequestIn, DietFeedbackIn, DietPlanRequestIn,
                              ExercisePlanRequestIn, FoodClarifyIn, FoodEntryIn, OperationResult, ProfileIn, ReadinessCheckInIn,
                              ReviewSummary)
from ..llm.gateway import LLMUnavailable
from ..repository.base import AuditStoreError
from ..rules.conflict_rules import Conflict, detect_conflicts
from ..util import new_id, utcnow
from .base import Agent, AgentContext
from .common import Halt, candidate_view, next_version
from .fitness_coach import FitnessCoach
from .nutrition_coach import NutritionCoach
from .safety_supervisor import NON_PERSONALISED_REPLY, ReviewResult, SafetySupervisor

MAX_RECONCILE_ROUNDS = 2


def fail_closed(fn):
    """AR-10: if an audit record cannot be stored anywhere in the flow, nothing personalised is released."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except AuditStoreError as e:
            self.trace("failClosed", f"Audit record could not be stored ({e}); failing closed — nothing personalised is released")
            try:
                self.repo.db.rollback()
                self.repo.save_trace(self.ctx.trace)
            except Exception:
                pass
            res = OperationResult(request_id=self.ctx.request_id, status=OutcomeStatus.SAFE_RESPONSE,
                                  message=NON_PERSONALISED_REPLY + f" (Reason: audit log unavailable — {e}.)",
                                  trace=self.ctx.trace.as_list(), extra={"fail_closed": True})
            return res if fn.__name__ not in ("submit_profile", "record_consent") else {"saved": False, "status": "FailClosed", "message": res.message}
    return wrapper
KIND_LABEL = {"diet": "diet plan", "exercise": "exercise plan", "integrated": "integrated daily plan", "food_analysis": "meal analysis"}


class Orchestrator(Agent):
    role = AgentRole.ORCHESTRATOR

    def __init__(self, ctx: AgentContext):
        super().__init__(ctx)
        self.nutrition = NutritionCoach(ctx)
        self.fitness = FitnessCoach(ctx)
        self.supervisor = SafetySupervisor(ctx)
        self.workers = [self.nutrition, self.fitness, self.supervisor]

    # ------------------------------------------------------------------ plumbing
    def dispatch(self, use_case: str, summary: str, detail: Optional[Dict[str, Any]] = None):
        self.trace("dispatch", f"{use_case}: {summary}", detail=detail)

    def result(self, status: OutcomeStatus, message: str, *, content: Optional[Dict[str, Any]] = None,
               review: Optional[ReviewSummary] = None, extra: Optional[Dict[str, Any]] = None) -> OperationResult:
        self.trace("notifyUser", f"{status.value}: {message[:90]}")
        self.repo.save_trace(self.ctx.trace)
        return OperationResult(request_id=self.ctx.request_id, status=status, message=message, content=content, review=review,
                               trace=self.ctx.trace.as_list(), extra=extra or {})

    def halt(self, h: Halt) -> OperationResult:
        if h.status == OutcomeStatus.CLARIFICATION:
            self.repo.notify("user", self.ctx.user_id, self.ctx.request_id, NotificationKind.CLARIFICATION, h.message)
        return self.result(h.status, h.message, content=h.content, extra=h.extra)

    def review_summary(self, case: m.ReviewCase) -> ReviewSummary:
        self.repo.db.refresh(case)
        last = case.decisions[-1] if case.decisions else None
        return ReviewSummary(case_id=case.id, state=case.state, decision=last.decision if last else None,
                             risk_level=last.risk_level if last else None, risk_score=last.risk_score if last else None,
                             score_breakdown=last.score_breakdown if last else {}, triggered_rules=last.triggered_rules if last else [],
                             policy_version=last.policy_version if last else None, repair_count=case.repair_count,
                             decisions=[{"decision": d.decision, "risk_level": d.risk_level, "risk_score": d.risk_score,
                                         "triggered_rules": d.triggered_rules, "candidate_version": d.candidate_version,
                                         "score_breakdown": d.score_breakdown, "revision_instructions": d.revision_instructions,
                                         "rationale": d.rationale, "at": d.created_at.isoformat()} for d in case.decisions])

    def check_preconditions(self, *, need_profile: bool = True, personalised: bool = True) -> Optional[OperationResult]:
        """Consent, profile and planning-pause gates shared by UC02–UC09 (UC02 2a, UC01 3a, AR-09)."""
        consents = self.repo.consents(self.ctx.user_id)
        if not consents.get(ConsentScope.CORE.value):
            self.trace("checkConsent", "Required processing consent absent or withdrawn — processing stopped (UC02 2a)")
            return self.result(OutcomeStatus.BLOCKED, "Required processing consent is not active. Please review and grant consent in your profile settings (UC01). "
                               "Nothing was processed.", extra={"next_action": "UC01 consent"})
        if need_profile and self.repo.reload_profile(self.ctx.user_id) is None:
            return self.result(OutcomeStatus.BLOCKED, "Please create your profile first (goals, allergies, limits, available time).", extra={"next_action": "UC01 profile"})
        if personalised:
            open_inc = self.repo.open_critical_incidents(self.ctx.user_id)
            if open_inc:
                self.trace("checkPlanningPause", f"Personalised planning is paused: {len(open_inc)} unacknowledged critical incident(s) (AR-09)")
                return self.result(OutcomeStatus.BLOCKED, "Personalised planning is paused after a critical safety event (" + open_inc[0].description[:120] +
                                   "). A support notice was issued and the operator has been notified; planning resumes once the incident has been reviewed. "
                                   "You can still record check-ins and activity feedback.", extra={"paused": True, "incident_id": open_inc[0].id})
        self.trace("checkConsent", "Processing consent verified; current profile loaded")
        return None

    # ================================================================== UC01
    @fail_closed
    def submit_profile(self, data: ProfileIn) -> Dict[str, Any]:
        self.dispatch("UC01", "profile submitted")
        payload = data.model_dump(exclude={"free_text", "confirm"})
        missing: List[str] = []
        conflicts: List[str] = []
        if data.allergy_status == AllergyStatus.UNKNOWN:
            missing.append("allergies (status unknown — not treated as 'no allergies')")
        if data.allergy_status == AllergyStatus.KNOWN and not data.allergies:
            conflicts.append("allergy status is 'known' but no allergies were listed")
        if data.allergy_status == AllergyStatus.NONE and data.allergies:
            conflicts.append("allergy status is 'none' but allergies were listed")
        if data.available_time_min is None:
            missing.append("available_time_min")
        if not data.goals:
            missing.append("goals")
        if data.free_text:
            try:
                draft = self.llm.interpret_constraints(payload, data.free_text)
                conflicts += [c for c in draft.detected_conflicts if c not in conflicts]
                missing += [f for f in draft.missing_safety_fields if not any(f in x for x in missing)]
                self.trace("interpretConstraints", f"LLM read the free text: {len(draft.detected_conflicts)} conflict(s), {len(draft.missing_safety_fields)} missing field(s)",
                           llm_used=True, detail=draft.model_dump())
            except LLMUnavailable as e:
                self.trace("interpretConstraints", f"LLM unavailable ({e}); structured fields only", llm_used=True)
        self.trace("checkSafetyFields", ("Missing: " + "; ".join(missing)) if missing else "All safety fields present", detail={"conflicts": conflicts})
        if conflicts:
            self.repo.save_trace(self.ctx.trace)
            return {"saved": False, "status": "Conflict", "conflicts": conflicts, "missing_fields": missing,
                    "message": "Please revise the conflicting entries: " + "; ".join(conflicts),
                    "trace": [t.model_dump() for t in self.ctx.trace.as_list()]}
        if not data.confirm:
            self.repo.save_trace(self.ctx.trace)
            return {"saved": False, "status": "AwaitingConfirmation", "missing_fields": missing, "proposed": payload,
                    "message": "Review the proposed profile and confirm to save a new version.",
                    "trace": [t.model_dump() for t in self.ctx.trace.as_list()]}
        status = ProfileStatus.INCOMPLETE if any(x.startswith("allergies") for x in missing) else ProfileStatus.ACTIVE
        prof = self.repo.save_profile(self.ctx.user_id, payload, status.value, missing, conflicts)
        self.audit("profileSaved", decision=status.value, versions={"profile_version": prof.version, "previous_version_id": prof.previous_version_id})
        self.trace("saveProfile", f"Profile v{prof.version} saved as {status.value}; only authorised information is visible to the Coaches")
        if status == ProfileStatus.INCOMPLETE:
            self.trace("restrictPlanning", "Allergy status unknown → personalised dietary planning restricted until clarified (UC01 4a)")
        self.repo.save_trace(self.ctx.trace)
        return {"saved": True, "status": status.value, "version": prof.version, "profile_id": prof.id, "missing_fields": missing,
                "message": f"Profile version {prof.version} saved ({status.value})." + (" Personalised dietary planning is restricted until allergy status is confirmed." if status == ProfileStatus.INCOMPLETE else ""),
                "trace": [t.model_dump() for t in self.ctx.trace.as_list()]}

    @fail_closed
    def record_consent(self, scope: str, granted: bool) -> Dict[str, Any]:
        self.dispatch("UC01", f"consent {scope} {'granted' if granted else 'withdrawn'}")
        prof = self.repo.reload_profile(self.ctx.user_id)
        rec = self.repo.record_consent(self.ctx.user_id, scope, granted, prof.version if prof else None)
        self.audit("consentRecorded", decision="granted" if granted else "withdrawn", versions={"scope": scope, "consent_id": rec.id if rec else None})
        if scope == ConsentScope.CORE.value and not granted:
            self.trace("stopNewProcessing", "Required consent withdrawn → affected automated processing stopped (UC01 3a)")
            if prof:
                prof.status = ProfileStatus.CONSENT_WITHDRAWN.value
                self.repo.commit()
        elif scope == ConsentScope.CORE.value and granted and prof and prof.status == ProfileStatus.CONSENT_WITHDRAWN.value:
            prof.status = ProfileStatus.INCOMPLETE.value if any(x.startswith("allergies") for x in prof.missing_fields) else ProfileStatus.ACTIVE.value
            self.repo.commit()
        self.repo.save_trace(self.ctx.trace)
        return {"scope": scope, "granted": granted, "consents": self.repo.consents(self.ctx.user_id),
                "message": ("Consent recorded." if granted else f"Consent for {scope} withdrawn. "
                            + ("Personalised processing is stopped until consent is granted again." if scope == "core" else "The optional feature stays disabled; core functions are unaffected."))}

    # ================================================================== UC02
    @fail_closed
    def record_meal(self, data: FoodEntryIn) -> OperationResult:
        self.dispatch("UC02", f"food entry ({data.input_type})")
        blocked = self.check_preconditions(need_profile=False)
        if blocked:
            return blocked
        entry, candidate, halt = self.nutrition.record_meal(data)
        return self._finish_food(entry, candidate, halt)

    @fail_closed
    def clarify_meal(self, entry_id: str, data: FoodClarifyIn) -> OperationResult:
        self.dispatch("UC02", "clarification answer")
        blocked = self.check_preconditions(need_profile=False)
        if blocked:
            return blocked
        entry = self.repo.get_food_entry(entry_id)
        if entry is None or entry.user_id != self.ctx.user_id:
            return self.result(OutcomeStatus.BLOCKED, "Food entry not found.")
        entry, candidate, halt = self.nutrition.clarify_entry(entry, data.answer)
        return self._finish_food(entry, candidate, halt)

    def _finish_food(self, entry, candidate, halt) -> OperationResult:
        if halt:
            res = self.halt(halt)
            if entry is not None:
                res.content = self._entry_view(entry)
            return res
        self.trace("queueAnalysisForReview", "Saved analysis candidate forwarded to UC10 with its evidence")
        outcome = self.run_review_pipeline(candidate, source_input=entry.raw_input)
        case_id = outcome.review.case_id if outcome.review else None
        summary = (outcome.content or {}).get("summary_text") or candidate.content.get("summary_text")
        self.nutrition.finalise_entry(entry, outcome.status, case_id, summary)
        outcome.content = {**(outcome.content or {}), **self._entry_view(entry)}
        if outcome.status == OutcomeStatus.RELEASED:
            outcome.message = "Your meal was analysed and the analysis passed the safety review. " + (summary or "")
        elif outcome.status in (OutcomeStatus.SAFE_RESPONSE, OutcomeStatus.WITHHELD):
            outcome.message = "Your meal was recorded, but the personalised analysis is not available: " + outcome.message
        return outcome

    @staticmethod
    def _entry_view(e: m.FoodEntry) -> Dict[str, Any]:
        return {"entry": {"id": e.id, "raw_input": e.raw_input, "input_type": e.input_type, "status": e.status, "version": e.version,
                          "items": e.items, "nutrient_estimate": e.nutrient_estimate, "uncertainty_range": e.uncertainty_range,
                          "confidence": e.confidence, "confidence_basis": e.confidence_basis, "safety_flags": e.safety_flags,
                          "clarifications": e.clarifications, "clarification_question": e.clarification_question,
                          "missing_evidence": e.missing_evidence, "released_analysis": e.released_analysis, "data_version": e.data_version,
                          "profile_version": e.profile_version, "model_version": e.model_version,
                          "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None}}

    # ================================================================== UC03 / UC04
    @fail_closed
    def request_diet_plan(self, req: DietPlanRequestIn) -> OperationResult:
        self.dispatch("UC03", "diet plan requested")
        blocked = self.check_preconditions()
        if blocked:
            return blocked
        plan_date = req.plan_date or date.today()
        candidate, halt = self.nutrition.generate_diet_candidate(plan_date, req)
        if halt:
            return self.halt(halt)
        return self.submit_candidate(candidate, source_input=req.notes or "")

    @fail_closed
    def submit_diet_feedback(self, fb: DietFeedbackIn) -> OperationResult:
        self.dispatch("UC04", "diet feedback")
        blocked = self.check_preconditions()
        if blocked:
            return blocked
        candidate, halt = self.nutrition.adapt_diet(fb)
        if halt:
            return self.halt(halt)
        outcome = self.submit_candidate(candidate, source_input=fb.text or "")
        self.nutrition.mark_feedback(candidate, outcome.status)
        if candidate.content.get("strategy") == "SafeAlternative":
            outcome.message = ("Your request for a stricter or compensatory plan was declined — plans are never made stricter to punish or "
                               "compensate for missed adherence or food already eaten. A feasible non-punitive alternative was prepared instead. ") + outcome.message
        elif outcome.status == OutcomeStatus.RELEASED and candidate.change_explanation:
            outcome.message += " Change: " + candidate.change_explanation
        return outcome

    # ================================================================== UC05 – UC08
    @fail_closed
    def submit_checkin(self, data: ReadinessCheckInIn) -> OperationResult:
        self.dispatch("UC05", "readiness check-in")
        blocked = self.check_preconditions(personalised=False)
        if blocked:
            return blocked
        assessment, halt = self.fitness.submit_checkin(data)
        if halt:
            res = self.halt(halt)
            if assessment is not None:
                res.content = self._assessment_view(assessment)
            return res
        # Rule-based status, not a recommendation → shown directly without UC10 (report §4.6 notes)
        return self.result(OutcomeStatus.INFO, f"Readiness today: {assessment.result}. " + " ".join(assessment.evidence[:2]),
                           content=self._assessment_view(assessment))

    @staticmethod
    def _assessment_view(a: m.ReadinessAssessment) -> Dict[str, Any]:
        return {"assessment": {"id": a.id, "result": a.result, "status": a.status, "restrictions": a.restrictions, "evidence": a.evidence,
                               "confidence": a.confidence, "profile_version": a.profile_version, "rule_version": a.rule_version,
                               "model_version": a.model_version, "clarification_fields": a.clarification_fields,
                               "created_at": a.created_at.isoformat() if a.created_at else None}}

    @fail_closed
    def request_exercise_plan(self, req: ExercisePlanRequestIn) -> OperationResult:
        self.dispatch("UC06", "exercise plan requested")
        blocked = self.check_preconditions()
        if blocked:
            return blocked
        plan_date = req.plan_date or date.today()
        pr = self.repo.create_planning_request(self.ctx.user_id, self.ctx.request_id, plan_date, RequestState.DRAFTING.value)
        candidate, halt = self.fitness.generate_exercise_candidate(plan_date, req.notes, planning_request=pr)
        if halt:
            pr.state = RequestState.DRAFTING.value if halt.status == OutcomeStatus.PENDING_READINESS else RequestState.ABANDONED.value
            self.repo.commit()
            return self.halt(halt)
        self.trace("submitToOrchestrator", f"Candidate v{candidate.version} accepted for UC09/UC10; user told the plan is awaiting review")
        pr.state = RequestState.PENDING_REVIEW.value
        self.repo.commit()
        outcome = self.submit_candidate(candidate, source_input=req.notes or "")
        pr.state = {OutcomeStatus.RELEASED: RequestState.RELEASED}.get(outcome.status, RequestState.WITHHELD).value
        pr.repair_count = outcome.review.repair_count if outcome.review else 0
        self.repo.commit()
        return outcome

    @fail_closed
    def submit_activity_feedback(self, item_id: str, fb: ActivityFeedbackIn) -> OperationResult:
        self.dispatch("UC07", "activity feedback")
        blocked = self.check_preconditions(personalised=False)
        if blocked:
            return blocked

        def on_critical(rule_ids: List[str], description: str) -> str:
            self.trace("flagForHardRule", "Feedback forwarded to the Safety Supervisor for hard-rule handling")
            return self.supervisor.handle_critical_input(self.ctx.user_id, rule_ids, description)

        row, halt, comparison = self.fitness.submit_activity_feedback(item_id, fb, on_critical)
        view = {"feedback": {"id": row.id, "completion": row.completion, "exertion": row.exertion, "pain": row.pain, "fatigue": row.fatigue,
                             "warning_signs": row.warning_signs, "recovery_summary": row.recovery_summary, "progression_hold": row.progression_hold,
                             "status": row.status}, "comparison": comparison} if row else None
        if halt:
            res = self.halt(halt)
            res.content = view
            return res
        msg = "Feedback recorded and available for readiness assessment and plan adaptation."
        if row.progression_hold:
            msg += " Progression of this activity is on hold because of the pain/warning signs you reported."
        return self.result(OutcomeStatus.INFO, msg, content=view)

    @fail_closed
    def request_plan_adaptation(self, req: AdaptRequestIn) -> OperationResult:
        self.dispatch("UC08", "exercise plan adaptation requested")
        blocked = self.check_preconditions()
        if blocked:
            return blocked
        candidate, halt = self.fitness.adapt_exercise(req.notes)
        if halt:
            return self.halt(halt)
        outcome = self.submit_candidate(candidate, source_input=req.notes or "")
        self.fitness.mark_adaptations(candidate, outcome.status)
        return outcome

    # ================================================================== UC09
    @fail_closed
    def request_daily_plan(self, req: DailyPlanRequestIn) -> OperationResult:
        self.dispatch("UC09", "integrated daily plan requested")
        blocked = self.check_preconditions()
        if blocked:
            return blocked
        plan_date = req.plan_date or date.today()
        profile = self.repo.reload_profile(self.ctx.user_id)
        self.trace("loadProfile", f"Latest authorised profile v{profile.version}")
        self.trace("requestCandidate", "Asking Nutrition Coach and Fitness Coach for today's candidates")
        diet, halt = self.nutrition.generate_diet_candidate(plan_date, DietPlanRequestIn(plan_date=plan_date))
        if halt:
            return self.halt(halt)
        exercise, halt = self.fitness.generate_exercise_candidate(plan_date, None)
        if halt:
            return self.halt(halt)
        integrated, failure = self.reconcile_plans(diet, exercise, source_input="")
        if integrated is None:
            return self.result(OutcomeStatus.NOT_INTEGRATED, failure or "The daily plan could not be integrated.",
                               extra={"diet_candidate_id": diet.id, "exercise_candidate_id": exercise.id})
        return self.run_review_pipeline(integrated, source_input="")

    def submit_candidate(self, candidate: m.PlanCandidate, *, source_input: str) -> OperationResult:
        """UC09 1a: a Coach submitted one candidate — reconcile with an accepted counterpart for the same day, else review alone."""
        if candidate.kind in (CandidateKind.DIET.value, CandidateKind.EXERCISE.value) and candidate.plan_date:
            other_kind = CandidateKind.EXERCISE.value if candidate.kind == CandidateKind.DIET.value else CandidateKind.DIET.value
            counterpart = self.repo.find_accepted_counterpart(candidate.user_id, candidate.plan_date, other_kind)
            if counterpart is not None:
                self.trace("findAcceptedCounterpart", f"Released {other_kind} plan v{counterpart.version} exists for {candidate.plan_date} → reconciling (UC09 1a)")
                diet, exercise = (candidate, counterpart) if candidate.kind == CandidateKind.DIET.value else (counterpart, candidate)
                integrated, failure = self.reconcile_plans(diet, exercise, source_input=source_input)
                if integrated is None:
                    candidate.status = CandidateStatus.WITHHELD.value
                    self.repo.commit()
                    return self.result(OutcomeStatus.NOT_INTEGRATED, failure or "The plan could not be integrated with today's released counterpart.")
                return self.run_review_pipeline(integrated, source_input=source_input)
            self.trace("findAcceptedCounterpart", f"No released {other_kind} plan for {candidate.plan_date} → single candidate goes to UC10 on its own")
        return self.run_review_pipeline(candidate, source_input=source_input)

    def reconcile_plans(self, diet: m.PlanCandidate, exercise: m.PlanCandidate, *, source_input: str) -> Tuple[Optional[m.PlanCandidate], Optional[str]]:
        profile = self.repo.reload_profile(self.ctx.user_id)
        readiness = self.repo.reload_latest_readiness(self.ctx.user_id, usable_only=True)
        if profile.available_time_min is None:
            self.trace("detectConflicts", "Available time unknown → cannot check workload; asking the user (UC09 4a)")
            self.repo.notify("user", self.ctx.user_id, self.ctx.request_id, NotificationKind.CLARIFICATION, "Please add your available time to your profile.")
            return None, "Missing information: your available time per day is not in your profile. Please add it (UC01); the plan will be checked again afterwards."
        seen: set = set()
        for rnd in range(1, MAX_RECONCILE_ROUNDS + 2):
            conflicts = detect_conflicts(diet.content, exercise.content, readiness.result if readiness else None, profile.available_time_min,
                                         diet.profile_version, exercise.profile_version)
            self.trace("detectConflicts", (f"Round {rnd}: {len(conflicts)} conflict(s): " + "; ".join(f"{c.type.value} ({c.responsible_agent.value})" for c in conflicts))
                       if conflicts else f"Round {rnd}: no timing, recovery, workload or nutrition conflict", detail={"conflicts": [c.__dict__ for c in conflicts]})
            if not conflicts:
                break
            types = {c.type for c in conflicts}
            if types & seen:
                self._record_conflicts(conflicts, rnd, resolved=False)
                return None, "The same conflict returned after a correction (" + ", ".join(t.value for t in types & seen) + "); the daily plan was not integrated. Nothing was released."
            if rnd > MAX_RECONCILE_ROUNDS:
                self._record_conflicts(conflicts, rnd, resolved=False)
                return None, "Conflicts could not be resolved within the allowed rounds; the daily plan was not integrated."
            seen |= types
            self._record_conflicts(conflicts, rnd, resolved=False)
            for c in conflicts:
                request_text, agent = self._classify(c)
                coach = self.nutrition if agent == AgentRole.NUTRITION_COACH else self.fitness
                target = diet if agent == AgentRole.NUTRITION_COACH else exercise
                if c.type == ConflictType.PROFILE_VERSION:
                    self.trace("requestRegeneration", f"{agent.value} used an older profile version → regenerate with v{profile.version}")
                corrected = coach.correct(target, request_text)
                if corrected is None:
                    return None, f"{agent.value} could not deliver a corrected candidate; the daily plan was not integrated."
                target.status = CandidateStatus.SUPERSEDED.value
                self.repo.commit()
                if agent == AgentRole.NUTRITION_COACH:
                    diet = corrected
                else:
                    exercise = corrected
            for pc in self.repo.conflicts_for_request(self.ctx.request_id):
                pc.resolved = True
            self.repo.commit()

        integrated = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.INTEGRATED.value,
                                     version=next_version(self.repo, self.ctx.user_id, CandidateKind.INTEGRATED.value), plan_date=diet.plan_date or exercise.plan_date,
                                     profile_version=diet.profile_version, rationale="Integrated daily plan: diet and exercise candidates reconciled by rule.",
                                     status=CandidateStatus.DRAFT.value, diet_candidate_id=diet.id, exercise_candidate_id=exercise.id, conflicts_resolved=True,
                                     model_version=self.model_version, agent_version=self.agent_id,
                                     content={"plan_date": (diet.plan_date or exercise.plan_date).isoformat(), "diet": diet.content, "exercise": exercise.content,
                                              "diet_candidate_id": diet.id, "diet_version": diet.version, "exercise_candidate_id": exercise.id,
                                              "exercise_version": exercise.version, "source_input": source_input,
                                              "conflicts_resolved": [{"type": pc.type, "description": pc.description, "round": pc.round}
                                                                     for pc in self.repo.conflicts_for_request(self.ctx.request_id)]})
        self.repo.save_candidate(integrated)
        for pc in self.repo.conflicts_for_request(self.ctx.request_id):
            pc.integrated_plan_id = integrated.id
        self.repo.commit()
        self.audit("integrationDecision", decision="Integrated", versions={"integrated_id": integrated.id, "diet_candidate_id": diet.id, "diet_version": diet.version,
                                                                          "exercise_candidate_id": exercise.id, "exercise_version": exercise.version,
                                                                          "profile_version": integrated.profile_version})
        self.trace("saveIntegratedPlan", f"Integrated plan v{integrated.version} saved (diet v{diet.version} + exercise v{exercise.version}); submitted to UC10 — not released yet")
        return integrated, None

    def _record_conflicts(self, conflicts: List[Conflict], rnd: int, *, resolved: bool):
        for c in conflicts:
            self.repo.save_conflict(m.PlanConflict(id=new_id("pc"), request_id=self.ctx.request_id, round=rnd, type=c.type.value, description=c.description,
                                                   responsible_agent=c.responsible_agent.value, resolved=resolved))

    def _classify(self, c: Conflict) -> Tuple[str, AgentRole]:
        """LLM may refine the classification and draft the request; the rule category is used if it is unavailable (UC09 5b)."""
        try:
            cls = self.llm.classify_conflict({"type": c.type.value, "description": c.description, "responsible_agent": c.responsible_agent.value}, {})
            self.trace("classifyConflict", f"LLM refined conflict → {cls.refined_type.value}, {cls.responsible_agent}: {cls.correction_request[:80]}", llm_used=True)
            agent = AgentRole(cls.responsible_agent) if cls.refined_type == c.type else c.responsible_agent
            return cls.correction_request, agent
        except LLMUnavailable as e:
            self.trace("useRuleCategory", f"LLM unavailable ({e}); routing by rule category {c.type.value}", llm_used=True)
            return f"Rule-based {c.type.value} conflict: {c.description}. Please correct your candidate.", c.responsible_agent

    # ================================================================== UC10 driver
    def _coach_for(self, candidate: m.PlanCandidate, instructions_text: str = "") -> Tuple[Agent, Optional[m.PlanCandidate]]:
        if candidate.kind == CandidateKind.DIET.value:
            return self.nutrition, candidate
        if candidate.kind in (CandidateKind.EXERCISE.value,):
            return self.fitness, candidate
        if candidate.kind == CandidateKind.INTEGRATED.value:
            text = instructions_text.lower()
            diet_words = ("meal", "kcal", "energy", "food", "allergen", "diet", "nutri", "unverified", "floor")
            exercise_words = ("intensity", "duration", "activity", "readiness", "exercise", "available time", "recovery day", "physical limits")
            diet_hits = sum(text.count(w) for w in diet_words)
            exercise_hits = sum(text.count(w) for w in exercise_words)
            if diet_hits > exercise_hits:
                return self.nutrition, self.repo.get_candidate(candidate.diet_candidate_id)
            return self.fitness, self.repo.get_candidate(candidate.exercise_candidate_id)
        return self.nutrition, candidate

    def run_review_pipeline(self, candidate: m.PlanCandidate, *, source_input: str) -> OperationResult:
        sup = self.supervisor
        case = sup.open_case(candidate)
        current = candidate
        while True:
            res: ReviewResult = sup.review_candidate(current, case, user_input_text=source_input)
            if res.fail_closed:
                msg = sup.non_personalised_reply()
                return self.result(OutcomeStatus.SAFE_RESPONSE, msg, review=self.review_summary(case))
            if res.decision == DecisionType.APPROVE:
                if sup.release(current, case, res):
                    self._release_components(current)
                    self.repo.notify("user", self.ctx.user_id, self.ctx.request_id, NotificationKind.RELEASE, f"Released: {KIND_LABEL.get(current.kind, current.kind)} v{current.version}. {res.reason}")
                    return self.result(OutcomeStatus.RELEASED, f"Your {KIND_LABEL.get(current.kind, current.kind)} (v{current.version}) passed the safety review and has been released. {res.reason}.",
                                       content=candidate_view(current), review=self.review_summary(case))
                return self.result(OutcomeStatus.WITHHELD, "Release was blocked: the version selected for release did not match the approved version.", review=self.review_summary(case))
            if res.decision == DecisionType.REVISE_AND_REVIEW:
                if case.repair_count < sup.max_repairs and res.revision is not None:
                    case.repair_count += 1
                    self.repo.commit()
                    self.trace("revisionRequested", f"Repair {case.repair_count}/{sup.max_repairs}: rule-linked revision sent to the responsible Coach")
                    # route by what the rules found (score reasons / rule messages), not by the model's prose
                    hint = " ".join(r for comp in ("S", "U", "P") for r in (res.score.reasons.get(comp, []) if res.score else []))
                    hint += " " + " ".join(t.message for t in res.triggered)
                    coach, component = self._coach_for(current, hint or " ".join(res.revision.instructions))
                    revised = coach.revise(component, res.revision) if component is not None else None
                    if revised is None:
                        sup.withhold(current, case, "responsible Coach could not produce a revision")
                        text = sup.prepare_safe_reply(current, case, res)
                        return self.result(OutcomeStatus.SAFE_RESPONSE if text else OutcomeStatus.WITHHELD, text or "The personalised plan was withheld.", review=self.review_summary(case))
                    current.status = CandidateStatus.SUPERSEDED.value
                    component.status = CandidateStatus.SUPERSEDED.value if component is not current else component.status
                    self.repo.commit()
                    if current.kind == CandidateKind.INTEGRATED.value:
                        diet = revised if revised.kind == CandidateKind.DIET.value else self.repo.get_candidate(current.diet_candidate_id)
                        exercise = revised if revised.kind == CandidateKind.EXERCISE.value else self.repo.get_candidate(current.exercise_candidate_id)
                        self.trace("reconcileAgain", "Revised component → integrated plan reconciled again before re-review (UC10 4a / AR-08)")
                        integrated, failure = self.reconcile_plans(diet, exercise, source_input=source_input)
                        if integrated is None:
                            sup.withhold(current, case, failure or "re-reconciliation failed")
                            return self.result(OutcomeStatus.NOT_INTEGRATED, failure or "The revised daily plan could not be integrated.", review=self.review_summary(case))
                        revised = integrated
                    revised.repair_count = case.repair_count
                    self.repo.commit()
                    current = revised
                    continue
                sup.withhold(current, case, f"revision limit ({sup.max_repairs}) reached")
                self.trace("revisionLimit", f"Revision limit of {sup.max_repairs} reached → personalised candidate withheld (UC10 4d)")
                text = sup.prepare_safe_reply(current, case, res)
                return self.result(OutcomeStatus.SAFE_RESPONSE if text else OutcomeStatus.WITHHELD,
                                   (text or "The personalised plan was withheld.") + f" (The plan could not be made safe within {sup.max_repairs} revisions.)",
                                   review=self.review_summary(case))
            if res.decision == DecisionType.SAFE_FALLBACK:
                text = sup.prepare_safe_reply(current, case, res)
                why = "; ".join(f"{t.id}: {t.message}" for t in res.triggered) or res.reason
                return self.result(OutcomeStatus.SAFE_RESPONSE if text else OutcomeStatus.WITHHELD, (text or "The personalised content was withheld.") + f" Reason: {why}.",
                                   review=self.review_summary(case))
            if res.decision == DecisionType.WITHHOLD:
                sup.withhold(current, case, res.reason)
                ids = res.triggered_ids()
                if "HR-05" in ids:
                    msg = "Your allergy status is unknown, so personalised dietary content is withheld. Please confirm it in your profile (UC01) and try again. An unknown status is never treated as 'no allergies'."
                elif "HR-07" in ids:
                    msg = "The candidate's evidence or profile version is not current, so it was withheld pending correction. Please try again."
                else:
                    msg = f"The personalised content was withheld: {res.reason}"
                return self.result(OutcomeStatus.WITHHELD, msg, review=self.review_summary(case), extra={"next_action": "UC01 profile" if "HR-05" in ids else None})
            if res.decision == DecisionType.CRITICAL_STOP:
                notice = sup.stop_personalised_planning(self.ctx.user_id, current, case, res.triggered_ids(), res.reason)
                return self.result(OutcomeStatus.SUPPORT_NOTICE, notice, review=self.review_summary(case))

    def _release_components(self, candidate: m.PlanCandidate):
        """An integrated plan release also activates its two component versions."""
        if candidate.kind != CandidateKind.INTEGRATED.value:
            return
        for cid, kind in ((candidate.diet_candidate_id, CandidateKind.DIET.value), (candidate.exercise_candidate_id, CandidateKind.EXERCISE.value)):
            comp = self.repo.get_candidate(cid) if cid else None
            if comp:
                comp.status, comp.released = CandidateStatus.RELEASED.value, True
                self.repo.commit()
                self.repo.supersede_released(candidate.user_id, kind, comp.id)
