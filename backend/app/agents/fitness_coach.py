"""FitnessCoach — UC05 readiness, UC06 exercise plan, UC07 activity feedback, UC08 plan adaptation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..db import models as m
from ..domain.enums import (INTENSITY_RANK, AdaptationAction, AdaptationStatus, AgentRole, AssessmentStatus, CandidateKind,
                            CandidateStatus, CompletionStatus, FeedbackRecordStatus, Intensity, OutcomeStatus, ReadinessResult,
                            RequestState)
from ..domain.schemas import ActivityFeedbackIn, ExercisePlanDraft, ReadinessCheckInIn, RevisionInstruction
from ..llm.gateway import LLMUnavailable
from ..rules import readiness_rules
from ..rules.load_rules import allowed_actions, check_load_increase, conservative_action
from ..rules.text_patterns import CRITICAL_SYMPTOM_PATTERNS, describe_hits, match_any
from ..util import new_id, utcnow
from .base import Agent
from .common import Halt, next_version, profile_context

READINESS_MAX_AGE_HOURS = 24
PAIN_CRITICAL = 7
PAIN_HOLD = 3


class FitnessCoach(Agent):
    role = AgentRole.FITNESS_COACH

    # ===================================================================== UC05
    @staticmethod
    def summarise_history(history: List[Dict[str, Any]]) -> str:
        if not history:
            return "No activity recorded in the app in the last 48 h."
        parts = []
        for h in history[:6]:
            bits = [f"{h['activity']} {h['planned_min']} min — {h['completion']}"]
            if h.get("exertion") is not None:
                bits.append(f"exertion {h['exertion']}/10")
            if h.get("pain"):
                bits.append(f"pain {h['pain']}/10")
            if h.get("warning_signs"):
                bits.append("warning signs: " + ", ".join(h["warning_signs"]))
            parts.append(f"{h['plan_date']}: " + ", ".join(bits))
        return "Recorded in the app (last 48 h): " + "; ".join(parts) + "."

    def submit_checkin(self, data: ReadinessCheckInIn) -> Tuple[Optional[m.ReadinessAssessment], Optional[Halt]]:
        profile = self.repo.reload_profile(self.ctx.user_id)
        checkin = data.model_dump()
        history = self.repo.recent_activity_records(self.ctx.user_id, hours=48)
        history_summary = self.summarise_history(history)
        self.trace("loadAuthorisedContext", f"Profile v{profile.version if profile else '-'} loaded; {len(history)} activity record(s) from the last 48 h "
                   "taken from the repository (the user only reports what the app does not know)", detail={"recorded_activity": history})
        assessment = m.ReadinessAssessment(id=new_id("ra"), user_id=self.ctx.user_id, request_id=self.ctx.request_id,
                                           status=AssessmentStatus.VALIDATING.value, profile_version=profile.version if profile else None,
                                           rule_version=readiness_rules.RULE_VERSION)
        checkin_row = m.ReadinessCheckIn(id=new_id("ci"), user_id=self.ctx.user_id, sleep_quality=data.sleep_quality, fatigue=data.fatigue,
                                         soreness=data.soreness, pain=data.pain, pain_affects_activity=data.pain_affects_activity,
                                         recent_activity=data.recent_activity, available_time_min=data.available_time_min, free_text=data.free_text)
        assessment.checkins.append(checkin_row)

        problems = readiness_rules.validate_checkin(checkin, has_recorded_activity=bool(history))
        if problems:
            assessment.status, assessment.clarification_fields = AssessmentStatus.AWAITING_CLARIFICATION.value, problems
            assessment.evidence = ["Missing or contradictory information is never treated as Ready."]
            self.repo.save_assessment(assessment)
            self.trace("checkCompletenessAndConsistency", "Check-in incomplete or contradictory → clarification requested (UC05 3a)", detail={"fields": problems})
            return assessment, Halt(OutcomeStatus.CLARIFICATION, "Please complete or correct: " + ", ".join(problems) + ". Missing information is never treated as Ready.",
                                    extra={"fields": problems, "assessment_id": assessment.id})

        active_restrictions = self.repo.active_recovery_restrictions(self.ctx.user_id)
        try:
            proposal = self.llm.assess_readiness(checkin, {"profile": profile_context(profile), "active_restrictions": active_restrictions,
                                                           "recorded_activity": history})
            self.trace("assessReadiness", "LLM interpreted the check-in: " + ("pain affects activity; " if proposal.pain_affects_activity else "")
                       + ("capacity reduced; " if proposal.capacity_reduced else "") + f"confidence {proposal.confidence:.2f}",
                       llm_used=True, detail=proposal.model_dump())
        except LLMUnavailable as e:
            self.trace("assessReadiness", f"LLM unavailable ({e}); assessment failed, nothing saved (UC05 4b)", llm_used=True)
            return None, Halt(OutcomeStatus.WITHHELD, "The readiness assessment could not be completed right now (interpretation unavailable). Nothing was saved.")

        decision = readiness_rules.decide(checkin, proposal.pain_affects_activity, proposal.capacity_reduced, proposal.recovery_restrictions,
                                          active_restrictions, has_recorded_activity=bool(history))
        assessment.result = decision.result.value if decision.result else None
        assessment.restrictions = decision.restrictions
        reported = (checkin.get("recent_activity") or "").strip()
        assessment.evidence = ([history_summary] + ([f"Reported by the user (not in the app): {reported}"] if reported else [])
                               + decision.evidence + [f"LLM evidence: {e}" for e in proposal.evidence[:6]])
        assessment.confidence, assessment.model_version = proposal.confidence, self.model_version
        assessment.status = AssessmentStatus.COMPLETED.value
        self.repo.save_assessment(assessment)
        self.audit("assessmentSaved", decision=assessment.result, versions={"assessment_id": assessment.id, "profile_version": assessment.profile_version,
                                                                             "rule_version": readiness_rules.RULE_VERSION})
        self.trace("applyReadinessRules", f"Fixed rules decided: {assessment.result}", detail={"rule_version": readiness_rules.RULE_VERSION,
                                                                                               "restrictions": decision.restrictions, "evidence": decision.evidence})
        self._last_explanation = " ".join(decision.evidence)
        return assessment, None

    # ===================================================================== UC06
    def _readiness_sufficient(self, readiness: Optional[m.ReadinessAssessment]) -> bool:
        if readiness is None or readiness.status != AssessmentStatus.COMPLETED.value or not readiness.result:
            return False
        return (utcnow() - readiness.created_at) <= timedelta(hours=READINESS_MAX_AGE_HOURS)

    def _exercise_content(self, draft: ExercisePlanDraft, plan_date: date, readiness: m.ReadinessAssessment, source_input: Optional[str]) -> Tuple[Dict[str, Any], List[m.ActivityItem]]:
        items: List[m.ActivityItem] = []
        acts: List[Dict[str, Any]] = []
        for i, a in enumerate(draft.activities):
            item = m.ActivityItem(id=new_id("act"), order_index=i, name=a.name, duration_min=a.duration_min, intensity=a.intensity.value, notes=a.notes)
            items.append(item)
            acts.append({"id": item.id, "name": a.name, "duration_min": a.duration_min, "intensity": a.intensity.value, "notes": a.notes, "paused": False})
        content = {"plan_date": plan_date.isoformat(), "session_time": draft.session_time, "activities": acts, "warm_up": draft.warm_up,
                   "rest": draft.rest, "cool_down": draft.cool_down, "alternatives": draft.alternatives, "difficulty": draft.difficulty,
                   "progression": draft.progression, "rationale": draft.rationale, "total_min": sum(a["duration_min"] for a in acts),
                   "readiness_result": readiness.result, "readiness_restrictions": readiness.restrictions, "assessment_id": readiness.id,
                   "source_input": source_input or ""}
        return content, items

    def generate_exercise_candidate(self, plan_date: date, notes: Optional[str], *, revision: Optional[List[str]] = None,
                                    correction: Optional[str] = None, previous: Optional[m.PlanCandidate] = None,
                                    planning_request: Optional[m.ExercisePlanningRequest] = None) -> Tuple[Optional[m.PlanCandidate], Optional[Halt]]:
        profile = self.repo.reload_profile(self.ctx.user_id)
        readiness = self.repo.reload_latest_readiness(self.ctx.user_id, usable_only=True)
        self.trace("loadProfileAndLatestReadiness", f"Profile v{profile.version if profile else '-'}; latest readiness: "
                   + (f"{readiness.result} ({(utcnow() - readiness.created_at).total_seconds() / 3600:.1f} h old)" if readiness else "none"))
        if not self._readiness_sufficient(readiness):
            placeholder = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.EXERCISE.value,
                                          version=next_version(self.repo, self.ctx.user_id, CandidateKind.EXERCISE.value), plan_date=plan_date,
                                          profile_version=profile.version if profile else None, status=CandidateStatus.PLACEHOLDER.value, is_placeholder=True,
                                          content={"note": "internal conservative placeholder — never released", "plan_date": plan_date.isoformat()},
                                          model_version=self.model_version, agent_version=self.agent_id,
                                          planning_request_id=planning_request.id if planning_request else None)
            self.repo.save_candidate(placeholder)
            self.trace("createInternalPlaceholder", "Readiness insufficient → internal placeholder kept, user asked to complete the check-in (UC06 3a)")
            return None, Halt(OutcomeStatus.PENDING_READINESS, "Before a personalised exercise plan can be prepared, please complete today's readiness check-in "
                              "(sleep, fatigue, soreness, pain, recent activity, available time). A conservative internal placeholder was kept; it is never released.",
                              extra={"next_action": "UC05 check-in", "placeholder_id": placeholder.id})

        context: Dict[str, Any] = {"profile": profile_context(profile), "plan_date": plan_date.isoformat(),
                                   "readiness": {"result": readiness.result, "restrictions": readiness.restrictions, "evidence": readiness.evidence,
                                                 "age_hours": round((utcnow() - readiness.created_at).total_seconds() / 3600, 1)},
                                   "available_time_min": (readiness.checkins[0].available_time_min if readiness.checkins and readiness.checkins[0].available_time_min else None)
                                   or (profile.available_time_min if profile else 30), "notes": notes or ""}
        if revision:
            context["revision_instructions"] = revision
        if correction:
            context["correction_request"] = correction
        if previous is not None:
            context["previous_candidate"], context["session_time"] = previous.content, previous.content.get("session_time")
        try:
            draft = self.llm.generate_exercise_candidate(context)
            self.trace("generateExerciseCandidate", f"LLM drafted {len(draft.activities)} activities at {draft.session_time}, difficulty: {draft.difficulty[:60]}"
                       + (" (revision)" if revision else "") + (" (correction)" if correction else ""), llm_used=True,
                       detail={"activities": [(a.name, a.duration_min, a.intensity.value) for a in draft.activities]})
        except LLMUnavailable as e:
            self.trace("generateExerciseCandidate", f"LLM unavailable ({e}); no plan generated (UC06 4b)", llm_used=True)
            if planning_request:
                planning_request.state = RequestState.ABANDONED.value
                self.repo.commit()
            return None, Halt(OutcomeStatus.WITHHELD, "No exercise plan could be generated right now (model unavailable). Nothing was released.")

        if not draft.activities:
            return None, Halt(OutcomeStatus.CLARIFICATION, "No suitable activity fits your current constraints. Please update available time, equipment or physical limits in your profile (UC01). Safety limits were not relaxed.")

        if (revision or correction) and previous is not None:
            draft = self._enforce_instructions(draft, previous, " ".join(revision or []) + " " + (correction or ""))

        content, items = self._exercise_content(draft, plan_date, readiness, notes)
        candidate = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.EXERCISE.value,
                                    version=next_version(self.repo, self.ctx.user_id, CandidateKind.EXERCISE.value), plan_date=plan_date,
                                    profile_version=profile.version if profile else None, rationale=draft.rationale, status=CandidateStatus.DRAFT.value,
                                    previous_version_id=previous.id if previous else None, content=content, model_version=self.model_version,
                                    agent_version=self.agent_id, assessment_id=readiness.id,
                                    planning_request_id=planning_request.id if planning_request else (previous.planning_request_id if previous else None),
                                    repair_count=(previous.repair_count + 1) if (previous and revision) else 0)
        candidate.activities = items
        self.repo.save_candidate(candidate)
        if planning_request:
            planning_request.state = RequestState.SUBMITTING.value
            self.repo.commit()
        self.audit("exerciseCandidateSaved", versions={"candidate_id": candidate.id, "candidate_version": candidate.version,
                                                          "profile_version": candidate.profile_version, "assessment_id": readiness.id})
        self.trace("saveCandidate", f"Exercise candidate v{candidate.version} saved ({content['total_min']} min, readiness {readiness.result})",
                   detail={"candidate_id": candidate.id})
        self._last_explanation = draft.difficulty
        return candidate, None

    def _enforce_instructions(self, draft: ExercisePlanDraft, previous: m.PlanCandidate, instr: str) -> ExercisePlanDraft:
        """A revision must actually resolve what it was asked to resolve; rules enforce it if the draft did not."""
        instr = instr.lower()
        prev_acts = [a for a in previous.content.get("activities", []) if not a.get("paused")]
        prev_rank = max([INTENSITY_RANK[Intensity(a["intensity"])] for a in prev_acts], default=0)
        prev_total = sum(int(a.get("duration_min", 0)) for a in prev_acts)
        by_rank = {v: k for k, v in INTENSITY_RANK.items()}
        changed = []
        if any(w in instr for w in ("intensity", "recovery", "light")):
            cap = max(0, prev_rank - 1) if "recovery" not in instr else 0
            for a in draft.activities:
                if INTENSITY_RANK[a.intensity] > cap:
                    a.intensity = by_rank[cap]; changed.append(f"{a.name} → {a.intensity.value}")
        if any(w in instr for w in ("duration", "shorter", "available time", "workload", "> 20 min")):
            limit = int(prev_total * 0.8) if "> 20 min" not in instr else 20
            total = sum(a.duration_min for a in draft.activities)
            while total > limit and draft.activities:
                longest = max(draft.activities, key=lambda a: a.duration_min)
                cut = min(longest.duration_min - 5, total - limit)
                if cut <= 0:
                    break
                longest.duration_min -= cut; total -= cut; changed.append(f"{longest.name} −{cut} min")
        if changed:
            self.trace("enforceRevision", "Draft did not fully follow the instructions; rules enforced: " + ", ".join(changed))
        return draft

    # ===================================================================== UC07
    def submit_activity_feedback(self, item_id: str, fb: ActivityFeedbackIn, on_critical: Callable[[List[str], str], str]
                                 ) -> Tuple[Optional[m.ActivityFeedback], Optional[Halt], Dict[str, Any]]:
        item = self.repo.get_activity_item(item_id)
        if item is None or item.candidate.user_id != self.ctx.user_id:
            return None, Halt(OutcomeStatus.BLOCKED, "Activity not found in your released plans."), {}
        self.trace("loadPlan", f"Planned activity '{item.name}' ({item.duration_min} min, {item.intensity}) loaded")

        problems = []
        if fb.completion != CompletionStatus.SKIPPED:
            for f in ("exertion", "pain", "fatigue"):
                if getattr(fb, f) is None:
                    problems.append(f)
        if fb.completion == CompletionStatus.SKIPPED and (fb.exertion or 0) >= 7:
            problems.append("exertion (high exertion reported for a skipped activity)")
        if problems:
            self.trace("checkFeedbackConsistency", "Feedback incomplete/contradictory → clarification requested (UC07 3a)", detail={"fields": problems})
            return None, Halt(OutcomeStatus.CLARIFICATION, "Please complete or correct: " + ", ".join(problems) + ".", extra={"fields": problems}), {}

        warning_signs: List[str] = []
        summary = None
        notes_interpreted = False
        if fb.recovery_notes:
            try:
                interp = self.llm.interpret_recovery_notes(fb.recovery_notes, {"activity": item.name})
                warning_signs, summary, notes_interpreted = interp.warning_signs, interp.summary, True
                self.trace("interpretRecoveryNotes", "LLM interpreted recovery notes: " + (", ".join(warning_signs) or "no warning signs"), llm_used=True, detail=interp.model_dump())
            except LLMUnavailable as e:
                self.trace("markNotesUninterpreted", f"LLM unavailable ({e}); notes stored uninterpreted, numeric fields still rule-checked", llm_used=True)
        critical_hits = match_any(fb.recovery_notes or "", CRITICAL_SYMPTOM_PATTERNS)  # never rely on the LLM alone for safety
        pain_rule = (fb.pain or 0) >= PAIN_CRITICAL or bool(critical_hits)
        progression_hold = (fb.pain or 0) >= PAIN_HOLD or bool(warning_signs) or pain_rule

        comparison = {"planned_min": item.duration_min, "planned_intensity": item.intensity, "completion": fb.completion.value,
                      "exertion": fb.exertion, "pain": fb.pain, "fatigue": fb.fatigue}
        row = m.ActivityFeedback(id=new_id("afb"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, activity_item_id=item.id,
                                 candidate_id=item.candidate_id, completion=fb.completion.value, exertion=fb.exertion, pain=fb.pain, fatigue=fb.fatigue,
                                 recovery_notes=fb.recovery_notes, warning_signs=warning_signs + ([f"red flag: {describe_hits(critical_hits)}"] if critical_hits else []),
                                 recovery_summary=summary, notes_interpreted=notes_interpreted, progression_hold=progression_hold,
                                 status=FeedbackRecordStatus.FLAGGED.value if pain_rule else FeedbackRecordStatus.RECORDED.value)
        self.repo.save_activity_feedback(row)
        self.audit("activityFeedbackSaved", decision=row.status, versions={"feedback_id": row.id, "activity_item_id": item.id, "candidate_id": item.candidate_id},
                   payload=comparison)
        self.trace("comparePlannedAndActual", f"{fb.completion.value} vs planned {item.duration_min} min {item.intensity}; stored summary", detail=comparison)
        if progression_hold:
            self.trace("stopProgression", f"Progression of '{item.name}' stopped (pain {fb.pain}/10" + (", warning signs" if warning_signs else "") + ")")
        if pain_rule:
            desc = f"UC07 pain rule on '{item.name}': pain {fb.pain}/10" + (f"; red flags: {describe_hits(critical_hits)}" if critical_hits else "")
            self.trace("applyPainRule", "Alarming feedback → UC10 hard-rule handling (UC07 4a)")
            notice = on_critical(["HR-02"], desc)
            return row, Halt(OutcomeStatus.SUPPORT_NOTICE, notice, extra={"feedback_id": row.id}), comparison
        return row, None, comparison

    # ===================================================================== UC08
    def adapt_exercise(self, notes: Optional[str]) -> Tuple[Optional[m.PlanCandidate], Optional[Halt]]:
        plan = self.repo.current_released(self.ctx.user_id, CandidateKind.EXERCISE.value)
        if plan is None:
            return None, Halt(OutcomeStatus.BLOCKED, "There is no released exercise plan to adapt yet. Request an exercise plan first.")
        feedback = self.repo.feedback_for_candidate(plan.id)
        readiness = self.repo.reload_latest_readiness(self.ctx.user_id, usable_only=True)
        self.trace("loadFeedbackReadinessAndPlan", f"Plan v{plan.version}, {len(feedback)} feedback record(s), readiness {readiness.result if readiness else 'none'}")
        if not feedback and readiness is None:
            return None, Halt(OutcomeStatus.CLARIFICATION, "Record how the planned activities went (completion, exertion, pain) or complete a readiness check-in first.")

        non_completion = self.repo.non_completion_count(self.ctx.user_id)
        pain_reported = any(((f.pain or 0) >= PAIN_HOLD) or f.warning_signs for f in feedback)
        fb_dicts = [{"activity_item_id": f.activity_item_id, "completion": f.completion, "exertion": f.exertion, "pain": f.pain, "fatigue": f.fatigue,
                     "warning_signs": f.warning_signs} for f in feedback]
        readiness_dict = {"result": readiness.result, "restrictions": readiness.restrictions} if readiness else {}
        proposal = None
        try:
            proposal = self.llm.propose_adaptations(fb_dicts, readiness_dict, plan.content)
            self.trace("proposeAdaptations", "LLM proposed: " + ", ".join(f"{i.action.value}" for i in proposal.items), llm_used=True, detail=proposal.model_dump())
        except LLMUnavailable as e:
            self.trace("proposeAdaptations", f"LLM unavailable ({e}); using conservative option for every activity", llm_used=True)

        allowed = allowed_actions(non_completion, pain_reported)
        decisions: List[m.AdaptationDecision] = []
        new_acts: List[Dict[str, Any]] = []
        items: List[m.ActivityItem] = []
        summary: List[str] = []
        for a in plan.content.get("activities", []):
            p = next((i for i in proposal.items if i.activity_item_id == a["id"]), None) if proposal else None
            proposed = p.action if p else conservative_action(non_completion, pain_reported)
            action = proposed if proposed in allowed else conservative_action(non_completion, pain_reported)
            item_fb = [f for f in feedback if f.activity_item_id == a["id"]]
            if any(f.progression_hold for f in item_fb):
                action = AdaptationAction.PAUSE
            reason = (p.reason if p else "conservative option (no model proposal)") + ("" if action == proposed else f" → rule limited to {action.value}")
            new = {"name": a["name"], "duration_min": a["duration_min"], "intensity": a["intensity"], "notes": a.get("notes"), "paused": False}
            if action == AdaptationAction.REDUCE:
                new["duration_min"] = (p.new_duration_min if p and p.new_duration_min else max(5, int(a["duration_min"] * 0.6)))
                new["duration_min"] = min(new["duration_min"], a["duration_min"])
            elif action == AdaptationAction.REPLACE:
                if p and p.replacement:
                    new.update({"name": p.replacement.name, "duration_min": min(p.replacement.duration_min, a["duration_min"]), "intensity": p.replacement.intensity.value, "notes": p.replacement.notes})
                else:
                    new.update({"name": f"Easier {a['name'].lower()}", "duration_min": max(5, int(a["duration_min"] * 0.8)), "intensity": Intensity.LIGHT.value})
            elif action == AdaptationAction.PAUSE:
                new["paused"] = True
            new_acts.append(new)
            summary.append(f"{a['name']}: {action.value} — {reason}")
            decisions.append(m.AdaptationDecision(id=new_id("ad"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, activity_item_id=a["id"],
                                                  source_candidate_id=plan.id, proposed_action=proposed.value, action=action.value, reason=reason,
                                                  status=AdaptationStatus.CHECKING_LOAD.value))
        self.trace("decideAdaptations", "; ".join(summary), detail={"allowed_actions": [x.value for x in allowed], "non_completion_count": non_completion, "pain_reported": pain_reported})

        ok, reasons = check_load_increase(plan.content.get("activities", []), new_acts)
        if not ok:
            for n, old in zip(new_acts, plan.content.get("activities", [])):
                n["duration_min"] = min(n["duration_min"], old["duration_min"])
                n["intensity"] = old["intensity"] if Intensity(n["intensity"]) != Intensity.LIGHT else n["intensity"]
            self.trace("applyLoadRule", "Unsafe load increase detected → revised to conservative load (UC08 3a)", detail={"reasons": reasons})
        else:
            self.trace("applyLoadRule", "No unsupported increase in load")
        if readiness and readiness.result == ReadinessResult.RECOVERY.value:
            for n in new_acts:
                n["intensity"], n["duration_min"] = Intensity.LIGHT.value, min(n["duration_min"], 15)
            self.trace("respectReadiness", "Recovery readiness → all activities light and ≤ 15 min")

        for i, n in enumerate(new_acts):
            item = m.ActivityItem(id=new_id("act"), order_index=i, name=n["name"], duration_min=n["duration_min"], intensity=n["intensity"], notes=n.get("notes"), paused=n["paused"])
            items.append(item)
            n["id"] = item.id
        content = {**plan.content, "activities": new_acts, "total_min": sum(n["duration_min"] for n in new_acts if not n["paused"]),
                   "adaptation_summary": summary, "source_input": notes or "", "readiness_result": readiness.result if readiness else plan.content.get("readiness_result")}
        candidate = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.EXERCISE.value,
                                    version=next_version(self.repo, self.ctx.user_id, CandidateKind.EXERCISE.value), plan_date=plan.plan_date,
                                    profile_version=self.repo.reload_profile(self.ctx.user_id).version, rationale="Adapted from recorded feedback and latest readiness.",
                                    status=CandidateStatus.DRAFT.value, previous_version_id=plan.id, content=content, model_version=self.model_version,
                                    agent_version=self.agent_id, assessment_id=readiness.id if readiness else plan.assessment_id,
                                    change_explanation="\n".join(summary))
        candidate.activities = items
        self.repo.save_candidate(candidate)
        for d in decisions:
            d.new_candidate_id, d.status = candidate.id, AdaptationStatus.SUBMITTING.value
            self.repo.save_adaptation(d)
        self.audit("exerciseRevisionSaved", versions={"candidate_id": candidate.id, "candidate_version": candidate.version, "previous_version_id": plan.id})
        self.trace("saveRevision", f"Adapted exercise candidate v{candidate.version} saved", detail={"candidate_id": candidate.id})
        self._last_explanation = "\n".join(summary)
        return candidate, None

    def mark_adaptations(self, candidate: m.PlanCandidate, outcome: OutcomeStatus):
        for d in self.repo.db.query(m.AdaptationDecision).filter(m.AdaptationDecision.new_candidate_id == candidate.id):
            d.status = AdaptationStatus.APPLIED.value if outcome == OutcomeStatus.RELEASED else AdaptationStatus.DISCARDED.value
        self.repo.commit()

    # ===================================================================== UC09 / UC10 call-backs
    def revise(self, candidate: m.PlanCandidate, instructions: RevisionInstruction) -> Optional[m.PlanCandidate]:
        self.trace("revisionRequested", f"Revising exercise candidate v{candidate.version} on rule-linked instructions {instructions.rule_ids}")
        cand, _ = self.generate_exercise_candidate(candidate.plan_date or date.today(), candidate.content.get("source_input"),
                                                   revision=instructions.instructions, previous=candidate)
        if cand:
            cand.change_explanation = f"Revised on Safety Supervisor instructions: {instructions.summary or '; '.join(instructions.instructions)}"
            self.repo.commit()
        return cand

    def correct(self, candidate: m.PlanCandidate, correction_request: str) -> Optional[m.PlanCandidate]:
        self.trace("requestCorrection", f"Correcting exercise candidate v{candidate.version}: {correction_request}")
        cand, _ = self.generate_exercise_candidate(candidate.plan_date or date.today(), candidate.content.get("source_input"),
                                                   correction=correction_request, previous=candidate)
        if cand:
            cand.change_explanation = f"Corrected after reconciliation: {correction_request}"
            self.repo.commit()
        return cand
