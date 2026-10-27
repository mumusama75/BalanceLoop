"""SafetySupervisor — UC10: review, rule-linked revision, bounded safe response, release (AR-07..AR-10).

Deterministic by construction: hard rules first, then the explainable score. The LLM is used
only to *draft* revision instructions (and never decides release).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..db import models as m
from ..domain.enums import (AgentRole, CandidateKind, CandidateStatus, DecisionType, NotificationKind, OutcomeStatus,
                            ReviewCaseState, RiskLevel)
from ..domain.schemas import RevisionInstruction
from ..llm.gateway import LLMUnavailable
from ..repository.base import AuditStoreError
from ..rules.hard_rules import RULE_VERSION as HARD_RULE_VERSION, ReviewSubject, TriggeredRule, apply_hard_rules
from ..rules.risk_scoring import RiskScore, classify, compute_risk_score
from ..util import new_id, utcnow
from .base import Agent, AgentContext
from .subject import build_subject


SAFE_TEMPLATES = {
    CandidateKind.DIET: ("We could not release a personalised diet plan right now. General guidance that applies to most adults: "
                         "keep three regular meals, include vegetables and a protein source at each, drink water through the day, "
                         "and avoid skipping meals. Your profile and records are kept; you can retry later."),
    CandidateKind.EXERCISE: ("We could not release a personalised exercise plan right now. General guidance: a short, easy walk "
                             "at a conversational pace and a few minutes of gentle stretching are suitable for most adults on most days. "
                             "Stop any activity that causes pain. Your records are kept; you can retry later."),
    CandidateKind.INTEGRATED: ("We could not release a personalised daily plan right now. General guidance: regular meals with "
                               "vegetables and protein, water through the day, and an easy walk if you feel well. Your records are kept."),
    CandidateKind.FOOD_ANALYSIS: ("Your meal has been recorded, but a personalised nutrient analysis could not be released right now. "
                                  "The original entry is kept and can be analysed later."),
}

SUPPORT_NOTICE = ("Based on what you reported, please stop the activity and rest. If symptoms such as chest pain, fainting, "
                  "breathlessness or severe pain continue, seek medical help now (in Australia call 000 for emergencies). "
                  "Personalised planning has been paused for your safety and our team has been notified. "
                  "This service provides lifestyle support only and is not a medical service.")

NON_PERSONALISED_REPLY = ("The safety review service is currently unavailable, so no personalised content can be released. "
                          "Your records are saved. General guidance: regular meals, water, and gentle movement if you feel well.")


@dataclass
class ReviewResult:
    decision: DecisionType
    risk_level: Optional[RiskLevel]
    score: Optional[RiskScore]
    triggered: List[TriggeredRule]
    decision_row: Optional[m.ReviewDecision]
    fail_closed: bool = False
    revision: Optional[RevisionInstruction] = None
    reason: str = ""

    def triggered_ids(self) -> List[str]:
        return [t.id for t in self.triggered]


class SafetySupervisor(Agent):
    role = AgentRole.SAFETY_SUPERVISOR

    # ------------------------------------------------------------ policy
    def load_policy(self) -> Optional[m.ReviewPolicy]:
        policy = self.repo.load_policy()
        required = self.ctx.settings.required_policy_version
        if policy is None:
            self.trace("loadPolicy", "No active review policy — failing closed", detail={"required": required})
            return None
        if policy.version != required:
            self.trace("loadPolicy", f"Active policy v{policy.version} ≠ required v{required} — failing closed")
            return None
        self.trace("loadPolicy", f"Review policy v{policy.version} loaded ({len(policy.hard_rules)} hard rules, max repairs {policy.max_repairs})")
        return policy

    @property
    def max_repairs(self) -> int:
        p = self.repo.load_policy()
        return p.max_repairs if p else 2

    # ------------------------------------------------------------ case management
    def open_case(self, candidate: m.PlanCandidate) -> m.ReviewCase:
        case = m.ReviewCase(id=new_id("rc"), request_id=self.ctx.request_id, user_id=candidate.user_id,
                            candidate_id=candidate.id, candidate_version=candidate.version, kind=candidate.kind,
                            state=ReviewCaseState.PENDING_VALIDATION.value, repair_count=0)
        self.repo.create_review_case(case)
        self.trace("receiveCandidate", f"Review case opened for {candidate.kind} candidate v{candidate.version}",
                   detail={"case_id": case.id, "candidate_id": candidate.id})
        return case

    def _set_state(self, case: m.ReviewCase, state: ReviewCaseState, final: Optional[str] = None):
        case.state = state.value
        if final:
            case.final_status, case.closed_at = final, utcnow()
        self.repo.commit()

    # ------------------------------------------------------------ the review itself (one version)
    def review_candidate(self, candidate: m.PlanCandidate, case: m.ReviewCase, *, user_input_text: str = "") -> ReviewResult:
        policy = self.load_policy()
        if policy is None:
            return self._fail_closed(candidate, case, "review policy unavailable or version mismatch")

        case.candidate_id, case.candidate_version = candidate.id, candidate.version
        self._set_state(case, ReviewCaseState.UNDER_REVIEW)

        subject = build_subject(candidate, self.ctx, user_input_text=user_input_text)
        self.trace("validateEvidence", "Evidence and versions checked",
                   detail={"profile_version": subject.profile_version, "current_profile_version": subject.current_profile_version,
                           "model_version": subject.model_version, "evidence_complete": subject.evidence_complete})

        triggered = apply_hard_rules(subject, policy.hard_rules)
        self.trace("applyHardRules", ("Triggered: " + ", ".join(f"{t.id}{'(critical)' if t.critical else ''}" for t in triggered))
                   if triggered else "No hard rule triggered",
                   detail={"rule_version": HARD_RULE_VERSION, "triggered": [t.__dict__ for t in triggered]})

        score: Optional[RiskScore] = None
        level: Optional[RiskLevel] = None
        revision: Optional[RevisionInstruction] = None

        if any(t.critical for t in triggered):
            decision, level = DecisionType.CRITICAL_STOP, RiskLevel.CRITICAL
            reason = "critical hard rule: " + "; ".join(f"{t.id} {t.message}" for t in triggered if t.critical)
        elif triggered:
            ids = {t.id for t in triggered}
            if ids <= {"HR-05", "HR-07"}:
                decision, reason = DecisionType.WITHHOLD, "withheld pending correction: " + "; ".join(f"{t.id} {t.message}" for t in triggered)
            else:
                decision, reason = DecisionType.SAFE_FALLBACK, "blocked by hard rule(s): " + "; ".join(f"{t.id} {t.message}" for t in triggered)
        else:
            score = compute_risk_score(subject)
            level = classify(score, False, policy.risk_thresholds)
            self.trace("computeRiskScore", f"R = {score.R} (S={score.S}, U={score.U}, V={score.V}, P={score.P}, B={score.B}) → {level.value}",
                       detail=score.breakdown())
            if level == RiskLevel.LOW:
                decision, reason = DecisionType.APPROVE, f"Low risk (R={score.R}); exact version v{candidate.version} approved"
            elif level == RiskLevel.MEDIUM:
                decision, reason = DecisionType.REVISE_AND_REVIEW, f"Medium risk (R={score.R}); rule-linked revision requested"
                revision = self._draft_revision(triggered, candidate, score)
                if revision is None:
                    decision, reason = DecisionType.SAFE_FALLBACK, "Medium risk but revision drafting unavailable — safe response instead (UC10 4a)"
            elif level == RiskLevel.HIGH:
                decision, reason = DecisionType.SAFE_FALLBACK, f"High risk (R={score.R}, S={score.S}); candidate blocked, bounded safe response"
            else:
                decision, reason = DecisionType.CRITICAL_STOP, f"Critical risk score (R={score.R})"

        self.trace("determineDecision", f"{decision.value}: {reason}")

        # Record the decision BEFORE it takes effect (AR-10). Critical stop is the one action that does not wait.
        row = m.ReviewDecision(id=new_id("rd"), case_id=case.id, candidate_id=candidate.id, candidate_version=candidate.version,
                               decision=decision.value, risk_score=score.R if score else None,
                               risk_level=level.value if level else None, score_breakdown=score.breakdown() if score else {},
                               triggered_rules=[t.id for t in triggered], policy_version=policy.version, rationale=reason,
                               revision_instructions=revision.model_dump() if revision else None)
        self.repo.add_decision(row)
        if decision != DecisionType.CRITICAL_STOP:
            try:
                self.audit("reviewDecision", decision=decision.value,
                           versions={"candidate_id": candidate.id, "candidate_version": candidate.version,
                                     "policy_version": policy.version, "hard_rule_version": HARD_RULE_VERSION,
                                     "profile_version": subject.profile_version, "candidate_model_version": subject.model_version},
                           payload={"triggered_rules": [t.id for t in triggered], "risk": score.breakdown() if score else None,
                                    "risk_level": level.value if level else None, "rationale": reason})
            except AuditStoreError as e:
                return self._fail_closed(candidate, case, f"audit record could not be stored ({e})", decision_row=row)

        state = {DecisionType.APPROVE: ReviewCaseState.APPROVED, DecisionType.REVISE_AND_REVIEW: ReviewCaseState.AWAITING_REVISION,
                 DecisionType.SAFE_FALLBACK: ReviewCaseState.CHECKING_SAFE_FALLBACK, DecisionType.WITHHOLD: ReviewCaseState.WITHHELD,
                 DecisionType.CRITICAL_STOP: ReviewCaseState.WITHHELD}[decision]
        self._set_state(case, state)
        return ReviewResult(decision, level, score, triggered, row, revision=revision, reason=reason)

    def _draft_revision(self, triggered: List[TriggeredRule], candidate: m.PlanCandidate, score: RiskScore) -> Optional[RevisionInstruction]:
        rules = [{"id": t.id, "message": t.message} for t in triggered]
        # Medium score without a hard rule: explain the score drivers as pseudo-rules so the Coach knows what to change
        for comp, reasons in score.reasons.items():
            for r in reasons:
                rules.append({"id": f"SCORE-{comp}", "message": r})
        try:
            rev = self.llm.draft_revision_instructions(rules, {"kind": candidate.kind, "version": candidate.version, "content": candidate.content})
            self.trace("draftRevisionInstructions", f"LLM drafted {len(rev.instructions)} rule-linked instruction(s)", llm_used=True,
                       detail=rev.model_dump())
            return rev
        except LLMUnavailable as e:
            self.trace("draftRevisionInstructions", f"LLM unavailable ({e}); cannot draft revision", llm_used=True)
            return None

    def _fail_closed(self, candidate: m.PlanCandidate, case: m.ReviewCase, why: str, decision_row: Optional[m.ReviewDecision] = None) -> ReviewResult:
        self.trace("failClosed", f"Fail-closed: {why}; nothing personalised is released")
        self._set_state(case, ReviewCaseState.WITHHELD, final="FailClosed")
        candidate.status = CandidateStatus.WITHHELD.value
        self.repo.commit()
        inc = m.Incident(id=new_id("inc"), user_id=candidate.user_id, request_id=self.ctx.request_id, candidate_id=candidate.id,
                         rule_id="POLICY", severity="governance", description=f"Fail-closed: {why}")
        try:
            self.repo.create_incident(inc)
            self.repo.notify("founder", None, self.ctx.request_id, NotificationKind.INCIDENT, f"Fail-closed on request {self.ctx.request_id}: {why}")
        except Exception:  # pragma: no cover - storage itself is failing
            pass
        return ReviewResult(DecisionType.WITHHOLD, None, None, [], decision_row, fail_closed=True, reason=why)

    # ------------------------------------------------------------ effects
    def release(self, candidate: m.PlanCandidate, case: m.ReviewCase, result: ReviewResult) -> bool:
        """Release the exact approved version (UC10 step 7; ext. 6a/7a)."""
        row = result.decision_row
        if row is None or row.decision != DecisionType.APPROVE.value or row.candidate_id != candidate.id or row.candidate_version != candidate.version:
            self.trace("release", "Blocked: version selected for release differs from the approved version (7a)")
            self.audit("releaseMismatch", decision="Blocked", payload={"candidate_id": candidate.id, "version": candidate.version})
            self._set_state(case, ReviewCaseState.WITHHELD, final="Blocked")
            return False
        try:
            self.audit("release", decision="Released", versions={"candidate_id": candidate.id, "candidate_version": candidate.version,
                                                                   "policy_version": row.policy_version})
        except AuditStoreError as e:
            self._fail_closed(candidate, case, f"release audit could not be stored ({e})", decision_row=row)
            return False
        candidate.status, candidate.released = CandidateStatus.RELEASED.value, True
        self.repo.commit()
        self.repo.supersede_released(candidate.user_id, candidate.kind, candidate.id)
        self._set_state(case, ReviewCaseState.RELEASED, final="Released")
        self.repo.notify("user", candidate.user_id, self.ctx.request_id, NotificationKind.RELEASE,
                         f"Your {candidate.kind.replace('_', ' ')} (v{candidate.version}) passed the safety review and has been released.")
        self.trace("release", f"Released {candidate.kind} v{candidate.version} with rationale")
        self._last_explanation = result.reason
        return True

    def prepare_safe_reply(self, candidate: m.PlanCandidate, case: m.ReviewCase, result: ReviewResult) -> Optional[str]:
        """Bounded template, itself checked against the hard rules (UC10 3b / 4b / 4d)."""
        template = SAFE_TEMPLATES[CandidateKind(candidate.kind)]
        probe = ReviewSubject(kind=CandidateKind(candidate.kind), candidate_id="safe-template", version=0, profile_version=1,
                              current_profile_version=1, output_text=template, model_version="template", allergy_status="known")
        policy = self.repo.load_policy()
        hits = apply_hard_rules(probe, policy.hard_rules if policy else [])
        hits = [h for h in hits if h.id in ("HR-04", "HR-06")]  # only content rules apply to a template
        candidate.status = CandidateStatus.WITHHELD.value
        self.repo.commit()
        if hits:
            self.trace("checkSafeFallback", "Safe template failed hard-rule check — withheld as well")
            self._set_state(case, ReviewCaseState.WITHHELD, final="Withheld")
            self.audit("safeFallback", decision="Withheld", payload={"reason": "template failed check"})
            return None
        try:
            self.audit("safeFallback", decision="SafeResponseReleased", payload={"blocked_candidate": candidate.id, "rules": result.triggered_ids()})
        except AuditStoreError:
            self._set_state(case, ReviewCaseState.WITHHELD, final="FailClosed")
            return None
        self._set_state(case, ReviewCaseState.RELEASED, final="SafeFallback")
        self.repo.notify("user", candidate.user_id, self.ctx.request_id, NotificationKind.SAFE_RESPONSE, template)
        self.trace("checkSafeFallback", "Bounded safe response passed its own hard-rule check and was released instead")
        return template

    def withhold(self, candidate: m.PlanCandidate, case: m.ReviewCase, reason: str):
        candidate.status = CandidateStatus.WITHHELD.value
        self.repo.commit()
        self._set_state(case, ReviewCaseState.WITHHELD, final="Withheld")
        try:
            self.audit("withhold", decision="Withheld", payload={"reason": reason, "candidate_id": candidate.id})
        except AuditStoreError:
            pass
        self.trace("withhold", f"Withheld: {reason}")

    def stop_personalised_planning(self, user_id: str, candidate: Optional[m.PlanCandidate], case: Optional[m.ReviewCase],
                                   rule_ids: List[str], description: str) -> str:
        """UC10 3a: support notice FIRST, then incident record and Founder notification."""
        self.repo.notify("user", user_id, self.ctx.request_id, NotificationKind.SUPPORT_NOTICE, SUPPORT_NOTICE)
        self.trace("stopPlanning", "Personalised planning stopped; support notice issued immediately")
        if candidate is not None:
            candidate.status = CandidateStatus.WITHHELD.value
            self.repo.commit()
        if case is not None:
            self._set_state(case, ReviewCaseState.WITHHELD, final="CriticalStop")
        inc = m.Incident(id=new_id("inc"), user_id=user_id, request_id=self.ctx.request_id,
                         candidate_id=candidate.id if candidate else None, rule_id=",".join(rule_ids) or None,
                         severity="critical", description=description)
        self.repo.create_incident(inc)
        try:
            self.audit("criticalStop", decision="CriticalStop", payload={"incident_id": inc.id, "rules": rule_ids, "description": description})
        except AuditStoreError:
            pass
        self.repo.notify("founder", None, self.ctx.request_id, NotificationKind.INCIDENT,
                         f"Critical incident {inc.id} for user {user_id}: {description}")
        self.trace("raiseIncident", f"Incident {inc.id} recorded and Founder notified", detail={"incident_id": inc.id})
        return SUPPORT_NOTICE

    def handle_critical_input(self, user_id: str, rule_ids: List[str], description: str) -> str:
        """Entry point for UC07 4a (pain / alarming feedback) — no candidate involved."""
        return self.stop_personalised_planning(user_id, None, None, rule_ids, description)

    def non_personalised_reply(self) -> str:
        self.repo.notify("user", self.ctx.user_id, self.ctx.request_id, NotificationKind.SAFE_RESPONSE, NON_PERSONALISED_REPLY)
        return NON_PERSONALISED_REPLY
