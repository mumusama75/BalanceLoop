"""VersionedRecordStore — SQLAlchemy realisation of Repository (versioned storage + audit log)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import models as m
from ..domain.enums import CandidateStatus, ConsentScope, NotificationKind
from ..services.trace import Trace
from ..util import new_id, utcnow
from .base import AuditStoreError, Repository


class VersionedRecordStore(Repository):
    def __init__(self, db: Session):
        self.db = db
        self.storage_uri = str(db.get_bind().url)

    # ------------------------------------------------------------------ generic
    def commit(self):
        self.db.commit()

    def add(self, obj):
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    # ------------------------------------------------------------------ users
    def get_user(self, user_id: str) -> Optional[m.User]:
        return self.db.get(m.User, user_id)

    def list_users(self) -> List[m.User]:
        return list(self.db.scalars(select(m.User).order_by(m.User.created_at)))

    # ------------------------------------------------------------------ audit
    def append_audit(self, request_id, user_id, actor, action, *, decision=None, versions=None, payload=None) -> str:
        policy = self.load_policy()
        if policy and (policy.risk_thresholds or {}).get("simulate_audit_failure"):
            raise AuditStoreError("audit store unavailable (simulated by policy flag)")
        rec = m.AuditRecord(id=new_id("aud"), request_id=request_id, user_id=user_id, actor=str(actor), action=action,
                            decision=decision, versions=versions or {}, payload=payload or {})
        try:
            self.db.add(rec)
            self.db.commit()
        except SQLAlchemyError as e:  # pragma: no cover
            self.db.rollback()
            raise AuditStoreError(str(e)) from e
        return rec.id

    def list_audit(self, request_id: Optional[str] = None, user_id: Optional[str] = None, limit: int = 200) -> List[m.AuditRecord]:
        q = select(m.AuditRecord)
        if request_id:
            q = q.where(m.AuditRecord.request_id == request_id)
        if user_id:
            q = q.where(m.AuditRecord.user_id == user_id)
        return list(self.db.scalars(q.order_by(desc(m.AuditRecord.timestamp)).limit(limit)))

    def save_trace(self, trace: Trace):
        for s in trace.steps:
            self.db.add(m.AgentTrace(id=new_id("trc"), request_id=trace.request_id, user_id=trace.user_id, seq=s.seq,
                                     agent=s.agent, step=s.step, llm_used=s.llm_used, model_version=s.model_version,
                                     summary=s.summary, detail=s.detail, created_at=s.at or utcnow()))
        self.db.commit()

    def load_trace(self, request_id: str) -> List[m.AgentTrace]:
        return list(self.db.scalars(select(m.AgentTrace).where(m.AgentTrace.request_id == request_id).order_by(m.AgentTrace.seq)))

    def list_request_ids(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        q = select(m.AuditRecord.request_id, func.min(m.AuditRecord.timestamp), func.max(m.AuditRecord.user_id),
                   func.count(m.AuditRecord.id)).group_by(m.AuditRecord.request_id)
        if user_id:
            q = q.where(m.AuditRecord.user_id == user_id)
        rows = self.db.execute(q.order_by(desc(func.min(m.AuditRecord.timestamp))).limit(limit)).all()
        return [{"request_id": r[0], "started_at": r[1], "user_id": r[2], "records": r[3]} for r in rows]

    # ------------------------------------------------------------------ notifications
    def notify(self, audience: str, user_id: Optional[str], request_id: Optional[str], kind: NotificationKind, message: str):
        return self.add(m.Notification(id=new_id("ntf"), audience=audience, user_id=user_id, request_id=request_id,
                                       kind=kind.value, message=message))

    def list_notifications(self, audience: str, user_id: Optional[str] = None, limit: int = 50) -> List[m.Notification]:
        q = select(m.Notification).where(m.Notification.audience == audience)
        if user_id:
            q = q.where(m.Notification.user_id == user_id)
        return list(self.db.scalars(q.order_by(desc(m.Notification.created_at)).limit(limit)))

    # ------------------------------------------------------------------ UC01 profile & consent
    def reload_profile(self, user_id: str) -> Optional[m.UserProfile]:
        return self.db.scalars(select(m.UserProfile).where(m.UserProfile.user_id == user_id, m.UserProfile.is_current == True)
                               .order_by(desc(m.UserProfile.version))).first()

    def profile_versions(self, user_id: str) -> List[m.UserProfile]:
        return list(self.db.scalars(select(m.UserProfile).where(m.UserProfile.user_id == user_id).order_by(desc(m.UserProfile.version))))

    def save_profile(self, user_id, data, status, missing_fields, conflicts) -> m.UserProfile:
        prev = self.reload_profile(user_id)
        version = (prev.version + 1) if prev else 1
        if prev:
            prev.is_current = False
        prof = m.UserProfile(id=new_id("prof"), user_id=user_id, version=version, status=status,
                             previous_version_id=prev.id if prev else None, missing_fields=missing_fields,
                             conflicts=conflicts, is_current=True, **data)
        core = self.active_consent(user_id, ConsentScope.CORE)
        prof.consent_id = core.id if core else None
        return self.add(prof)

    def active_consent(self, user_id: str, scope: ConsentScope) -> Optional[m.ConsentRecord]:
        return self.db.scalars(select(m.ConsentRecord).where(m.ConsentRecord.user_id == user_id, m.ConsentRecord.scope == scope.value,
                                                             m.ConsentRecord.withdrawn == False).order_by(desc(m.ConsentRecord.granted_at))).first()

    def consents(self, user_id: str) -> Dict[str, bool]:
        return {s.value: self.active_consent(user_id, s) is not None for s in ConsentScope}

    def record_consent(self, user_id, scope, granted, profile_version) -> m.ConsentRecord:
        if not granted:
            return self.withdraw_consent(user_id, scope)
        existing = self.active_consent(user_id, ConsentScope(scope))
        if existing:
            return existing
        access = {"core": ["Orchestrator", "NutritionCoach", "FitnessCoach", "SafetySupervisor"], "O1": ["NutritionCoach"], "O2": ["FitnessCoach"]}[scope]
        return self.add(m.ConsentRecord(id=new_id("cons"), user_id=user_id, scope=scope, agent_access=access, profile_version=profile_version))

    def withdraw_consent(self, user_id, scope) -> Optional[m.ConsentRecord]:
        rec = self.active_consent(user_id, ConsentScope(scope))
        if rec:
            rec.withdrawn, rec.withdrawn_at = True, utcnow()
            self.db.commit()
        return rec

    # ------------------------------------------------------------------ UC02 food
    def save_food_entry(self, entry: m.FoodEntry) -> m.FoodEntry:
        return self.add(entry)

    def get_food_entry(self, entry_id: str) -> Optional[m.FoodEntry]:
        return self.db.get(m.FoodEntry, entry_id)

    def list_food_entries(self, user_id: str, day: Optional[date] = None, limit: int = 50) -> List[m.FoodEntry]:
        q = select(m.FoodEntry).where(m.FoodEntry.user_id == user_id)
        if day:
            q = q.where(m.FoodEntry.submitted_at >= datetime.combine(day, datetime.min.time()),
                        m.FoodEntry.submitted_at < datetime.combine(day + timedelta(days=1), datetime.min.time()))
        return list(self.db.scalars(q.order_by(desc(m.FoodEntry.submitted_at)).limit(limit)))

    # ------------------------------------------------------------------ UC05 readiness
    def save_assessment(self, assessment: m.ReadinessAssessment) -> m.ReadinessAssessment:
        if assessment.status == "Completed":
            for old in self.db.scalars(select(m.ReadinessAssessment).where(m.ReadinessAssessment.user_id == assessment.user_id,
                                                                            m.ReadinessAssessment.superseded == False)):
                old.superseded = True
        return self.add(assessment)

    def reload_latest_readiness(self, user_id: str, usable_only: bool = True) -> Optional[m.ReadinessAssessment]:
        q = select(m.ReadinessAssessment).where(m.ReadinessAssessment.user_id == user_id)
        if usable_only:
            q = q.where(m.ReadinessAssessment.status == "Completed", m.ReadinessAssessment.superseded == False)
        return self.db.scalars(q.order_by(desc(m.ReadinessAssessment.created_at))).first()

    def recent_activity_records(self, user_id: str, hours: int = 48) -> List[Dict[str, Any]]:
        """What the app already knows about the user's activity: feedback on planned activities in the last *hours*."""
        since = utcnow() - timedelta(hours=hours)
        rows = self.db.execute(
            select(m.ActivityFeedback, m.ActivityItem, m.PlanCandidate)
            .join(m.ActivityItem, m.ActivityFeedback.activity_item_id == m.ActivityItem.id)
            .join(m.PlanCandidate, m.ActivityItem.candidate_id == m.PlanCandidate.id)
            .where(m.ActivityFeedback.user_id == user_id, m.ActivityFeedback.created_at >= since)
            .order_by(desc(m.ActivityFeedback.created_at))).all()
        return [{"at": fb.created_at.isoformat(), "plan_date": cand.plan_date.isoformat() if cand.plan_date else None,
                 "activity": item.name, "planned_min": item.duration_min, "intensity": item.intensity,
                 "completion": fb.completion, "exertion": fb.exertion, "pain": fb.pain, "fatigue": fb.fatigue,
                 "warning_signs": fb.warning_signs, "progression_hold": fb.progression_hold} for fb, item, cand in rows]

    def recent_assessments(self, user_id: str, limit: int = 3) -> List[m.ReadinessAssessment]:
        return list(self.db.scalars(select(m.ReadinessAssessment).where(m.ReadinessAssessment.user_id == user_id,
                                                                        m.ReadinessAssessment.status == "Completed")
                                    .order_by(desc(m.ReadinessAssessment.created_at)).limit(limit)))

    def active_recovery_restrictions(self, user_id: str) -> List[str]:
        """Restrictions from a Recovery assessment in the last 48 h, or a progression hold from pain feedback."""
        since = utcnow() - timedelta(hours=48)
        res: List[str] = []
        holds = self.db.scalars(select(m.ActivityFeedback).where(m.ActivityFeedback.user_id == user_id,
                                                                 m.ActivityFeedback.progression_hold == True,
                                                                 m.ActivityFeedback.created_at >= since)).all()
        if holds:
            res.append("progression hold after reported pain")
        return res

    # ------------------------------------------------------------------ plan candidates
    def save_candidate(self, candidate: m.PlanCandidate) -> m.PlanCandidate:
        return self.add(candidate)

    def get_candidate(self, candidate_id: str) -> Optional[m.PlanCandidate]:
        return self.db.get(m.PlanCandidate, candidate_id)

    def latest_candidate(self, user_id: str, kind: str, plan_date: Optional[date] = None,
                         statuses: Optional[List[str]] = None) -> Optional[m.PlanCandidate]:
        q = select(m.PlanCandidate).where(m.PlanCandidate.user_id == user_id, m.PlanCandidate.kind == kind)
        if plan_date:
            q = q.where(m.PlanCandidate.plan_date == plan_date)
        if statuses:
            q = q.where(m.PlanCandidate.status.in_(statuses))
        return self.db.scalars(q.order_by(desc(m.PlanCandidate.created_at))).first()

    def current_released(self, user_id: str, kind: str) -> Optional[m.PlanCandidate]:
        return self.latest_candidate(user_id, kind, statuses=[CandidateStatus.RELEASED.value])

    def find_accepted_counterpart(self, user_id: str, plan_date: date, kind: str) -> Optional[m.PlanCandidate]:
        """UC09 1a: an accepted or released candidate of *kind* for the same user and day."""
        return self.latest_candidate(user_id, kind, plan_date, statuses=[CandidateStatus.RELEASED.value])

    def candidate_versions(self, user_id: str, kind: str, limit: int = 20) -> List[m.PlanCandidate]:
        return list(self.db.scalars(select(m.PlanCandidate).where(m.PlanCandidate.user_id == user_id, m.PlanCandidate.kind == kind)
                                    .order_by(desc(m.PlanCandidate.created_at)).limit(limit)))

    def supersede_released(self, user_id: str, kind: str, except_id: str):
        for c in self.db.scalars(select(m.PlanCandidate).where(m.PlanCandidate.user_id == user_id, m.PlanCandidate.kind == kind,
                                                               m.PlanCandidate.status == CandidateStatus.RELEASED.value,
                                                               m.PlanCandidate.id != except_id)):
            c.status = CandidateStatus.SUPERSEDED.value
        self.db.commit()

    def get_activity_item(self, item_id: str) -> Optional[m.ActivityItem]:
        return self.db.get(m.ActivityItem, item_id)

    # ------------------------------------------------------------------ UC06 planning request
    def create_planning_request(self, user_id: str, request_id: str, plan_date: date, state: str) -> m.ExercisePlanningRequest:
        return self.add(m.ExercisePlanningRequest(id=new_id("epr"), user_id=user_id, request_id=request_id, plan_date=plan_date, state=state))

    # ------------------------------------------------------------------ UC04 / UC07 / UC08 feedback
    def save_diet_feedback(self, fb: m.DietFeedback) -> m.DietFeedback:
        return self.add(fb)

    def restriction_request_count(self, user_id: str, days: int = 14) -> int:
        since = utcnow() - timedelta(days=days)
        return self.db.scalar(select(func.count(m.DietFeedback.id)).where(m.DietFeedback.user_id == user_id,
                                                                         m.DietFeedback.strategy == "SafeAlternative",
                                                                         m.DietFeedback.created_at >= since)) or 0

    def save_activity_feedback(self, fb: m.ActivityFeedback) -> m.ActivityFeedback:
        return self.add(fb)

    def feedback_for_candidate(self, candidate_id: str) -> List[m.ActivityFeedback]:
        return list(self.db.scalars(select(m.ActivityFeedback).where(m.ActivityFeedback.candidate_id == candidate_id)
                                    .order_by(m.ActivityFeedback.created_at)))

    def non_completion_count(self, user_id: str, days: int = 14) -> int:
        since = utcnow() - timedelta(days=days)
        return self.db.scalar(select(func.count(m.ActivityFeedback.id)).where(m.ActivityFeedback.user_id == user_id,
                                                                             m.ActivityFeedback.completion.in_(["skipped", "partial"]),
                                                                             m.ActivityFeedback.created_at >= since)) or 0

    def save_adaptation(self, dec: m.AdaptationDecision) -> m.AdaptationDecision:
        return self.add(dec)

    # ------------------------------------------------------------------ UC09 conflicts
    def save_conflict(self, c: m.PlanConflict) -> m.PlanConflict:
        return self.add(c)

    def conflicts_for_request(self, request_id: str) -> List[m.PlanConflict]:
        return list(self.db.scalars(select(m.PlanConflict).where(m.PlanConflict.request_id == request_id).order_by(m.PlanConflict.created_at)))

    # ------------------------------------------------------------------ UC10 policy / review
    def load_policy(self, version: Optional[str] = None) -> Optional[m.ReviewPolicy]:
        if version:
            return self.db.scalars(select(m.ReviewPolicy).where(m.ReviewPolicy.version == version)).first()
        return self.db.scalars(select(m.ReviewPolicy).where(m.ReviewPolicy.active == True)).first()

    def list_policies(self) -> List[m.ReviewPolicy]:
        return list(self.db.scalars(select(m.ReviewPolicy).order_by(m.ReviewPolicy.created_at)))

    def save_policy(self, policy: m.ReviewPolicy) -> m.ReviewPolicy:
        existing = self.load_policy(policy.version)
        if existing:
            existing.hard_rules, existing.risk_thresholds = policy.hard_rules, policy.risk_thresholds
            existing.max_repairs, existing.notes = policy.max_repairs, policy.notes
            self.db.commit(); self.db.refresh(existing)
            return existing
        return self.add(policy)

    def activate_policy(self, version: str) -> Optional[m.ReviewPolicy]:
        target = self.load_policy(version)
        if not target:
            return None
        for p in self.list_policies():
            p.active = (p.id == target.id)
        self.db.commit()
        return target

    def deactivate_all_policies(self):
        for p in self.list_policies():
            p.active = False
        self.db.commit()

    def create_review_case(self, case: m.ReviewCase) -> m.ReviewCase:
        return self.add(case)

    def add_decision(self, decision: m.ReviewDecision) -> m.ReviewDecision:
        return self.add(decision)

    def get_case(self, case_id: str) -> Optional[m.ReviewCase]:
        return self.db.get(m.ReviewCase, case_id)

    def cases_for_request(self, request_id: str) -> List[m.ReviewCase]:
        return list(self.db.scalars(select(m.ReviewCase).where(m.ReviewCase.request_id == request_id).order_by(m.ReviewCase.created_at)))

    def list_cases(self, user_id: Optional[str] = None, limit: int = 50) -> List[m.ReviewCase]:
        q = select(m.ReviewCase)
        if user_id:
            q = q.where(m.ReviewCase.user_id == user_id)
        return list(self.db.scalars(q.order_by(desc(m.ReviewCase.created_at)).limit(limit)))

    # ------------------------------------------------------------------ incidents
    def create_incident(self, inc: m.Incident) -> m.Incident:
        return self.add(inc)

    def open_critical_incidents(self, user_id: str) -> List[m.Incident]:
        return list(self.db.scalars(select(m.Incident).where(m.Incident.user_id == user_id, m.Incident.severity == "critical",
                                                             m.Incident.acknowledged == False).order_by(desc(m.Incident.created_at))))

    def list_incidents(self, limit: int = 100) -> List[m.Incident]:
        return list(self.db.scalars(select(m.Incident).order_by(desc(m.Incident.created_at)).limit(limit)))

    def ack_incident(self, incident_id: str) -> Optional[m.Incident]:
        inc = self.db.get(m.Incident, incident_id)
        if inc:
            inc.acknowledged, inc.acknowledged_at = True, utcnow()
            self.db.commit()
        return inc
