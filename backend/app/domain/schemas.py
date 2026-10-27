"""Pydantic schemas.

Two families live here:
* **LLM output schemas** — every LLMGateway method returns one of these. The JSON
  schema is sent to the model and the reply is validated; a reply that does not
  validate counts as "LLM unavailable" (AR-07: structured, checkable I/O).
* **API schemas** — request bodies and the uniform ``OperationResult`` envelope.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .enums import (AdaptationAction, AllergyStatus, CompletionStatus, ConflictType, Intensity, OutcomeStatus,
                    ReadinessResult)


# ============================================================ LLM output schemas
class FoodItemInterpretation(BaseModel):
    name: str = Field(description="Best-guess food name, plain English, singular")
    portion_description: Optional[str] = Field(default=None, description="Portion as the user described it")
    grams_estimate: Optional[float] = Field(default=None, ge=0)
    grams_low: Optional[float] = Field(default=None, ge=0)
    grams_high: Optional[float] = Field(default=None, ge=0)
    preparation: Optional[str] = None
    identification_confidence: float = Field(ge=0, le=1)
    portion_evidence: Literal["stated", "inferred", "none"] = "none"


class FoodInterpretation(BaseModel):
    items: List[FoodItemInterpretation] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    unidentifiable: bool = False
    notes: Optional[str] = None


class ProfileDraft(BaseModel):
    detected_conflicts: List[str] = Field(default_factory=list)
    missing_safety_fields: List[str] = Field(default_factory=list)
    summary: str = ""


class MealItemDraft(BaseModel):
    food: str
    grams: float = Field(gt=0)


class MealDraft(BaseModel):
    name: str
    time: str = Field(description="HH:MM 24h")
    items: List[MealItemDraft]
    notes: Optional[str] = None


class SubstitutionDraft(BaseModel):
    for_item: str = Field(alias="for")
    alternative: str
    reason: str
    model_config = {"populate_by_name": True}


class DietPlanDraft(BaseModel):
    meals: List[MealDraft]
    substitutions: List[SubstitutionDraft] = Field(default_factory=list)
    rationale: str
    constraints_explanation: str = ""
    uncertainties: List[str] = Field(default_factory=list)


class BarrierProposal(BaseModel):
    barrier: Literal["hunger", "satiety", "cost", "difficulty", "timing", "preference", "other"]
    punitive_request_detected: bool = False
    explanation: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


class DietRevisionDraft(BaseModel):
    plan: DietPlanDraft
    change_explanation: str
    changed_elements: List[str] = Field(default_factory=list)


class ReadinessProposal(BaseModel):
    evidence: List[str] = Field(default_factory=list)
    pain_affects_activity: bool = False
    capacity_reduced: bool = False
    recovery_restrictions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


class ActivityDraft(BaseModel):
    name: str
    duration_min: int = Field(gt=0, le=180)
    intensity: Intensity
    notes: Optional[str] = None


class ExercisePlanDraft(BaseModel):
    session_time: str = Field(description="HH:MM 24h")
    activities: List[ActivityDraft]
    warm_up: str
    rest: str
    cool_down: str
    alternatives: List[str] = Field(default_factory=list)
    difficulty: str
    progression: str = ""
    rationale: str


class RecoveryInterpretation(BaseModel):
    warning_signs: List[str] = Field(default_factory=list)
    pain_related: bool = False
    summary: str = ""


class AdaptationProposalItem(BaseModel):
    activity_item_id: str
    action: AdaptationAction
    reason: str
    new_duration_min: Optional[int] = Field(default=None, gt=0, le=180)
    replacement: Optional[ActivityDraft] = None


class AdaptationProposal(BaseModel):
    items: List[AdaptationProposalItem]
    summary: str = ""


class ConflictClassification(BaseModel):
    refined_type: ConflictType
    responsible_agent: Literal["NutritionCoach", "FitnessCoach"]
    correction_request: str


class RevisionInstruction(BaseModel):
    instructions: List[str]
    rule_ids: List[str] = Field(default_factory=list)
    summary: str = ""


# ============================================================ API: shared envelope
class TraceStep(BaseModel):
    seq: int
    at: Optional[datetime] = None
    agent: str
    step: str
    llm_used: bool = False
    model_version: Optional[str] = None
    summary: str
    detail: Dict[str, Any] = Field(default_factory=dict)


class ReviewSummary(BaseModel):
    case_id: str
    state: str
    decision: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[int] = None
    score_breakdown: Dict[str, Any] = Field(default_factory=dict)
    triggered_rules: List[str] = Field(default_factory=list)
    policy_version: Optional[str] = None
    repair_count: int = 0
    decisions: List[Dict[str, Any]] = Field(default_factory=list)


class OperationResult(BaseModel):
    """Uniform reply of every personalised operation (UC02–UC10)."""
    request_id: str
    status: OutcomeStatus
    message: str
    content: Optional[Dict[str, Any]] = None
    review: Optional[ReviewSummary] = None
    trace: List[TraceStep] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


# ============================================================ API: UC01
class ProfileIn(BaseModel):
    goals: List[str] = Field(default_factory=list)
    dietary_preferences: List[str] = Field(default_factory=list)
    allergy_status: AllergyStatus = AllergyStatus.UNKNOWN
    allergies: List[str] = Field(default_factory=list)
    physical_limits: List[str] = Field(default_factory=list)
    available_time_min: Optional[int] = Field(default=None, ge=0, le=600)
    equipment: List[str] = Field(default_factory=list)
    budget_level: Optional[Literal["low", "medium", "high"]] = None
    cultural_preferences: Optional[str] = None
    schedule_notes: Optional[str] = None
    cooking_skill: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    free_text: Optional[str] = Field(default=None, description="Optional free description; interpreted by the LLM")
    confirm: bool = Field(default=True, description="User confirmed the proposed changes (UC01 step 5)")


class ConsentIn(BaseModel):
    scope: Literal["core", "O1", "O2"]
    granted: bool = True


class ProfileOut(BaseModel):
    id: str
    user_id: str
    version: int
    status: str
    goals: List[str]
    dietary_preferences: List[str]
    allergy_status: str
    allergies: List[str]
    physical_limits: List[str]
    available_time_min: Optional[int]
    equipment: List[str]
    budget_level: Optional[str]
    cultural_preferences: Optional[str]
    schedule_notes: Optional[str]
    cooking_skill: Optional[str]
    missing_fields: List[str]
    conflicts: List[str]
    previous_version_id: Optional[str]
    saved_at: datetime
    consents: Dict[str, bool] = Field(default_factory=dict)
    model_config = {"from_attributes": True}


# ============================================================ API: UC02
class FoodEntryIn(BaseModel):
    text: str = Field(min_length=1, description="Meal description or selected food name")
    input_type: Literal["text", "selection", "image"] = "text"
    consumed_at: Optional[datetime] = None


class FoodClarifyIn(BaseModel):
    answer: str = Field(min_length=1)


# ============================================================ API: UC03 / UC04
class DietPlanRequestIn(BaseModel):
    plan_date: Optional[date] = None
    budget_level: Optional[Literal["low", "medium", "high"]] = None
    available_ingredients: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class DietFeedbackIn(BaseModel):
    hunger: Optional[int] = Field(default=None, ge=0, le=10)
    satiety: Optional[int] = Field(default=None, ge=0, le=10)
    cost_issue: bool = False
    adherence: Optional[Literal["full", "partial", "missed"]] = None
    text: Optional[str] = None


# ============================================================ API: UC05
class ReadinessCheckInIn(BaseModel):
    sleep_quality: Optional[int] = Field(default=None, ge=1, le=5)
    fatigue: Optional[int] = Field(default=None, ge=0, le=10)
    soreness: Optional[int] = Field(default=None, ge=0, le=10)
    pain: Optional[int] = Field(default=None, ge=0, le=10)
    pain_affects_activity: Optional[bool] = None
    recent_activity: Optional[str] = Field(default=None, description="Optional: activity today before this check-in, or anything the app has no record of (e.g. 'cycled 10 min to work'). Activity recorded through the app is loaded automatically.")
    available_time_min: Optional[int] = Field(default=None, ge=0, le=600)
    free_text: Optional[str] = None


# ============================================================ API: UC06 / UC07 / UC08
class ExercisePlanRequestIn(BaseModel):
    plan_date: Optional[date] = None
    notes: Optional[str] = None


class ActivityFeedbackIn(BaseModel):
    completion: CompletionStatus
    exertion: Optional[int] = Field(default=None, ge=0, le=10)
    pain: Optional[int] = Field(default=None, ge=0, le=10)
    fatigue: Optional[int] = Field(default=None, ge=0, le=10)
    recovery_notes: Optional[str] = None


class AdaptRequestIn(BaseModel):
    notes: Optional[str] = None


# ============================================================ API: UC09
class DailyPlanRequestIn(BaseModel):
    plan_date: Optional[date] = None


# ============================================================ API: Founder
class PolicyIn(BaseModel):
    version: str
    hard_rules: List[Dict[str, Any]]
    risk_thresholds: Dict[str, Any]
    max_repairs: int = Field(default=2, ge=0, le=5)
    notes: Optional[str] = None
    activate: bool = False


class UserOut(BaseModel):
    id: str
    display_name: str
    role: str
    model_config = {"from_attributes": True}
