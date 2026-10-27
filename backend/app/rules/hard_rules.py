"""UC10 hard rules — applied before any scoring; deterministic (AR-07).

Each rule has a predicate over a ``ReviewSubject``. Whether a rule is enabled and
whether it is *critical* comes from the active ReviewPolicy, so the Founder can
tune the policy without touching code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..domain.enums import INTENSITY_RANK, CandidateKind, Intensity, ReadinessResult
from .punitive_rules import CALORIE_FLOOR_KCAL, check_plan_not_punitive, detect_punitive_output
from .text_patterns import CRITICAL_SYMPTOM_PATTERNS, MEDICAL_CLAIM_PATTERNS, SELF_HARM_ED_PATTERNS, describe_hits, match_any

RULE_VERSION = "hard-rules-1.0"


@dataclass
class ReviewSubject:
    """Everything the Safety Supervisor needs to review one candidate version."""
    kind: CandidateKind
    candidate_id: str
    version: int
    profile_version: Optional[int]
    current_profile_version: Optional[int]
    content: Dict[str, Any] = field(default_factory=dict)
    output_text: str = ""                      # all user-facing text of the candidate
    directive_text: Optional[str] = None       # plan body only (meals, activities, notes); defaults to output_text
    user_input_text: str = ""                  # the user's own words that led here
    allergies: List[str] = field(default_factory=list)
    allergy_status: str = "unknown"
    physical_limits: List[str] = field(default_factory=list)
    readiness_result: Optional[str] = None
    readiness_age_hours: Optional[float] = None
    evidence_complete: bool = True
    model_version: Optional[str] = None
    allergen_hits: List[Dict[str, str]] = field(default_factory=list)   # [{food, allergen}]
    unverified_foods: List[str] = field(default_factory=list)
    total_duration_min: int = 0
    max_intensity: Optional[str] = None
    available_time_min: Optional[int] = None
    total_kcal: Optional[float] = None
    meals_count: int = 0
    previous_total_kcal: Optional[float] = None
    confidence: Optional[float] = None
    non_completion_count: int = 0
    restriction_request_count: int = 0
    pain_reported: Optional[int] = None
    warning_signs: List[str] = field(default_factory=list)
    coach_flags: List[Dict[str, Any]] = field(default_factory=list)   # [{code, severity, note}]

    @property
    def max_intensity_rank(self) -> int:
        return INTENSITY_RANK[Intensity(self.max_intensity)] if self.max_intensity else -1


@dataclass
class TriggeredRule:
    id: str
    critical: bool
    message: str


# ---- predicates -------------------------------------------------------------
def _hr01_allergen(s: ReviewSubject) -> Optional[str]:
    if s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED) and s.allergen_hits:
        return "recommended food contains an authorised allergen: " + "; ".join(f"{h['food']} ({h['allergen']})" for h in s.allergen_hits)
    return None


def _hr02_critical_symptoms(s: ReviewSubject) -> Optional[str]:
    hits = match_any(s.user_input_text, CRITICAL_SYMPTOM_PATTERNS)
    if (s.pain_reported is not None and s.pain_reported >= 7) or hits:
        parts = []
        if s.pain_reported is not None and s.pain_reported >= 7:
            parts.append(f"pain {s.pain_reported}/10")
        if hits:
            parts.append("warning signs: " + describe_hits(hits))
        return "; ".join(parts)
    return None


def _hr03_recovery_ignored(s: ReviewSubject) -> Optional[str]:
    if s.kind in (CandidateKind.EXERCISE, CandidateKind.INTEGRATED) and s.readiness_result == ReadinessResult.RECOVERY.value:
        if s.max_intensity_rank > INTENSITY_RANK[Intensity.LIGHT]:
            return f"readiness is Recovery but plan contains {s.max_intensity} intensity activity"
    return None


def _hr04_punitive(s: ReviewSubject) -> Optional[str]:
    reasons = []
    if s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED) and s.total_kcal is not None:
        reasons += check_plan_not_punitive(s.total_kcal, s.meals_count, s.previous_total_kcal)
    hit, desc = detect_punitive_output(s.directive_text if s.directive_text is not None else s.output_text)
    if hit:
        reasons.append(f"output contains punitive/compensatory instructions ({desc})")
    for fl in s.coach_flags:
        if fl.get("code") == "punitive":
            reasons.append(fl.get("note", "coach flagged punitive content"))
    return "; ".join(reasons) if reasons else None


def _hr05_allergy_unknown(s: ReviewSubject) -> Optional[str]:
    if s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED, CandidateKind.FOOD_ANALYSIS) and s.allergy_status == "unknown":
        return "allergy status is unknown — not treated as 'no allergies'; personalised dietary content withheld"
    return None


def _hr06_medical_claims(s: ReviewSubject) -> Optional[str]:
    hits = match_any(s.output_text, MEDICAL_CLAIM_PATTERNS, negation_aware=True)
    return ("output contains diagnostic/treatment claims: " + describe_hits(hits)) if hits else None


def _hr07_evidence(s: ReviewSubject) -> Optional[str]:
    problems = []
    if not s.evidence_complete:
        problems.append("evidence incomplete")
    if not s.model_version:
        problems.append("model version missing")
    if s.profile_version is None:
        problems.append("profile version missing")
    elif s.current_profile_version is not None and s.profile_version != s.current_profile_version:
        problems.append(f"candidate built on profile v{s.profile_version} but current is v{s.current_profile_version}")
    return "; ".join(problems) if problems else None


def _hr08_self_harm(s: ReviewSubject) -> Optional[str]:
    hits = match_any(s.user_input_text, SELF_HARM_ED_PATTERNS)
    return ("user input shows self-harm / disordered-eating warning signs: " + describe_hits(hits)) if hits else None


HARD_RULES: Dict[str, Callable[[ReviewSubject], Optional[str]]] = {
    "HR-01": _hr01_allergen,
    "HR-02": _hr02_critical_symptoms,
    "HR-03": _hr03_recovery_ignored,
    "HR-04": _hr04_punitive,
    "HR-05": _hr05_allergy_unknown,
    "HR-06": _hr06_medical_claims,
    "HR-07": _hr07_evidence,
    "HR-08": _hr08_self_harm,
}

DEFAULT_POLICY_HARD_RULES: List[Dict[str, Any]] = [
    {"id": "HR-01", "critical": False, "enabled": True, "description": "Recommended meal contains an authorised allergen"},
    {"id": "HR-02", "critical": True, "enabled": True, "description": "Pain ≥ 7/10 or red-flag symptom reported (chest pain, fainting, breathlessness…)"},
    {"id": "HR-03", "critical": False, "enabled": True, "description": "Readiness = Recovery but plan contains non-light activity"},
    {"id": "HR-04", "critical": False, "enabled": True, "description": "Punitive / compensatory restriction (energy below floor, skipped meals, exercise to offset food)"},
    {"id": "HR-05", "critical": False, "enabled": True, "description": "Allergy status unknown while producing personalised dietary content"},
    {"id": "HR-06", "critical": False, "enabled": True, "description": "Output contains diagnostic or treatment claims"},
    {"id": "HR-07", "critical": False, "enabled": True, "description": "Evidence / versions missing or profile version outdated (withhold, request correction)"},
    {"id": "HR-08", "critical": True, "enabled": True, "description": "Self-harm or disordered-eating warning signs in user input"},
]


def apply_hard_rules(subject: ReviewSubject, policy_rules: List[Dict[str, Any]]) -> List[TriggeredRule]:
    """Evaluate the enabled rules of the policy, in policy order."""
    triggered: List[TriggeredRule] = []
    for cfg in policy_rules:
        if not cfg.get("enabled", True):
            continue
        pred = HARD_RULES.get(cfg["id"])
        if pred is None:
            continue
        msg = pred(subject)
        if msg:
            triggered.append(TriggeredRule(cfg["id"], bool(cfg.get("critical", False)), msg))
    return triggered
