"""SQLAlchemy models — one table per persistent class of the Stage 1 class diagram.

Column naming follows MySQL conventions (snake_case, explicit FKs) so that the
SQLite prototype can be pointed at MySQL later by changing only the URL.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..util import utcnow
from .database import Base


# ---------------------------------------------------------------- User & profile
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | founder
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserProfile(Base):
    """A new row is written on every successful save (versioned, AR-01)."""
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_profile_user_version"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))  # ProfileStatus
    goals: Mapped[List[str]] = mapped_column(JSON, default=list)
    dietary_preferences: Mapped[List[str]] = mapped_column(JSON, default=list)
    allergy_status: Mapped[str] = mapped_column(String(10), default="unknown")  # AllergyStatus
    allergies: Mapped[List[str]] = mapped_column(JSON, default=list)
    physical_limits: Mapped[List[str]] = mapped_column(JSON, default=list)
    available_time_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    equipment: Mapped[List[str]] = mapped_column(JSON, default=list)
    budget_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # low | medium | high
    cultural_preferences: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    schedule_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cooking_skill: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    missing_fields: Mapped[List[str]] = mapped_column(JSON, default=list)
    conflicts: Mapped[List[str]] = mapped_column(JSON, default=list)
    previous_version_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    consent_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scope: Mapped[str] = mapped_column(String(10))  # core | O1 | O2
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    agent_access: Mapped[List[str]] = mapped_column(JSON, default=list)
    profile_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- UC02 Food entry
class FoodEntry(Base):
    __tablename__ = "food_entries"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    raw_input: Mapped[str] = mapped_column(Text)
    input_type: Mapped[str] = mapped_column(String(10), default="text")  # text | selection | image
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    items: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    portion: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    clarifications: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    nutrient_estimate: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    uncertainty_range: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_basis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    safety_flags: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="Draft")  # FoodEntryStatus
    version: Mapped[int] = mapped_column(Integer, default=1)
    data_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    profile_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    clarification_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    missing_evidence: Mapped[List[str]] = mapped_column(JSON, default=list)
    released_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_case_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


# ---------------------------------------------------------------- UC05 Readiness
class ReadinessAssessment(Base):
    __tablename__ = "readiness_assessments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    result: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # ReadinessResult
    status: Mapped[str] = mapped_column(String(30))  # AssessmentStatus
    restrictions: Mapped[List[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[List[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profile_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rule_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    clarification_fields: Mapped[List[str]] = mapped_column(JSON, default=list)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checkins: Mapped[List["ReadinessCheckIn"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class ReadinessCheckIn(Base):
    __tablename__ = "readiness_checkins"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("readiness_assessments.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sleep_quality: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # 1-5
    fatigue: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)         # 0-10
    soreness: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)        # 0-10
    pain: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)            # 0-10
    pain_affects_activity: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    recent_activity: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    available_time_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    free_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    assessment: Mapped["ReadinessAssessment"] = relationship(back_populates="checkins")


# ---------------------------------------------------------------- UC06 Planning request
class ExercisePlanningRequest(Base):
    __tablename__ = "exercise_planning_requests"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    plan_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(30))  # RequestState
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- Plan candidates
class PlanCandidate(Base):
    """Abstract PlanCandidate + its three specialisations, stored in one table.

    ``kind`` selects the specialisation: diet | exercise | integrated | food_analysis.
    Kind-specific content (meals, warm-up, ...) lives in ``content`` (JSON); exercise
    activities are additionally normalised into ``activity_items`` because feedback
    and adaptation decisions reference individual items.
    """
    __tablename__ = "plan_candidates"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    plan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    profile_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="Draft")  # CandidateStatus
    previous_version_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_flags: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    model_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    # exercise specialisation
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    planning_request_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # diet specialisation
    change_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # integrated specialisation
    diet_candidate_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    exercise_candidate_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    conflicts_resolved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    activities: Mapped[List["ActivityItem"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="ActivityItem.order_index")


class ActivityItem(Base):
    __tablename__ = "activity_items"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("plan_candidates.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    duration_min: Mapped[int] = mapped_column(Integer)
    intensity: Mapped[str] = mapped_column(String(20))  # Intensity
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate: Mapped["PlanCandidate"] = relationship(back_populates="activities")


# ---------------------------------------------------------------- UC04 / UC07 / UC08 feedback
class DietFeedback(Base):
    __tablename__ = "diet_feedback"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    candidate_id: Mapped[str] = mapped_column(String(40))
    hunger: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    satiety: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    adherence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30))  # FeedbackStatus
    strategy: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityFeedback(Base):
    __tablename__ = "activity_feedback"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    activity_item_id: Mapped[str] = mapped_column(ForeignKey("activity_items.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(40), index=True)
    completion: Mapped[str] = mapped_column(String(20))  # CompletionStatus
    exertion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pain: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fatigue: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recovery_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warning_signs: Mapped[List[str]] = mapped_column(JSON, default=list)
    recovery_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes_interpreted: Mapped[bool] = mapped_column(Boolean, default=False)
    progression_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30))  # FeedbackRecordStatus
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdaptationDecision(Base):
    __tablename__ = "adaptation_decisions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    activity_item_id: Mapped[str] = mapped_column(String(40))
    source_candidate_id: Mapped[str] = mapped_column(String(40))
    new_candidate_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    proposed_action: Mapped[str] = mapped_column(String(20))  # what the LLM proposed
    action: Mapped[str] = mapped_column(String(20))           # what the rules allowed
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30))  # AdaptationStatus
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- UC09 conflicts
class PlanConflict(Base):
    __tablename__ = "plan_conflicts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    integrated_plan_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(String(30))  # ConflictType
    description: Mapped[str] = mapped_column(Text)
    responsible_agent: Mapped[str] = mapped_column(String(30))
    llm_refined: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- UC10 review & audit
class ReviewPolicy(Base):
    __tablename__ = "review_policies"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True)
    hard_rules: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    risk_thresholds: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    max_repairs: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewCase(Base):
    __tablename__ = "review_cases"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(40), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30))  # ReviewCaseState
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    final_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decisions: Mapped[List["ReviewDecision"]] = relationship(back_populates="case", order_by="ReviewDecision.created_at")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("review_cases.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(40), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))  # DecisionType
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    score_breakdown: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    triggered_rules: Mapped[List[str]] = mapped_column(JSON, default=list)
    policy_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revision_instructions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    case: Mapped["ReviewCase"] = relationship(back_populates="decisions")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="critical")
    description: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(40))      # agent or "System" / "Founder"
    action: Mapped[str] = mapped_column(String(80))
    decision: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    versions: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentTrace(Base):
    """One step of the agent pipeline for a request (demo / explainability)."""
    __tablename__ = "agent_traces"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    seq: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(30))
    step: Mapped[str] = mapped_column(String(80))
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Messages shown to the user (release / safe response / support notice) or the Founder."""
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    audience: Mapped[str] = mapped_column(String(10), default="user")  # user | founder
    user_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # NotificationKind
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
