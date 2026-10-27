"""UC10 explainable risk score  R = 2S + U + V + P + B  (0–15). Prototype policy, not clinical."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..domain.enums import INTENSITY_RANK, CandidateKind, Intensity, ReadinessResult, RiskLevel
from .hard_rules import ReviewSubject
from .punitive_rules import CALORIE_FLOOR_KCAL

DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "critical_min": 11,   # R 11-15 -> Critical
    "high_min": 7,        # R 7-10 or S = 3 -> High
    "medium_min": 4,      # R 4-6 -> Medium ; 0-3 -> Low
    "severity_high": 3,
}


@dataclass
class RiskScore:
    S: int
    U: int
    V: int
    P: int
    B: int
    reasons: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def R(self) -> int:
        return 2 * self.S + self.U + self.V + self.P + self.B

    def breakdown(self) -> Dict[str, Any]:
        return {"S": self.S, "U": self.U, "V": self.V, "P": self.P, "B": self.B, "R": self.R,
                "formula": "R = 2S + U + V + P + B", "reasons": self.reasons}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def compute_risk_score(s: ReviewSubject) -> RiskScore:
    reasons: Dict[str, List[str]] = {"S": [], "U": [], "V": [], "P": [], "B": []}

    # S — severity of the worst plausible harm (0-3)
    S = 0
    if s.kind in (CandidateKind.EXERCISE, CandidateKind.INTEGRATED):
        rank = s.max_intensity_rank
        if rank >= 0:
            S = max(S, rank)  # light 0, light-moderate 1, moderate 2, vigorous 3
            reasons["S"].append(f"max intensity {s.max_intensity} -> {rank}")
        if s.physical_limits and rank >= 2:
            S = max(S, min(3, rank + 1)); reasons["S"].append("physical limits recorded and moderate-or-higher activity")
        if s.readiness_result == ReadinessResult.REDUCED.value and rank >= 1:
            S = max(S, 2); reasons["S"].append("Reduced readiness with non-light activity")
    if s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED) and s.total_kcal:
        if s.total_kcal < CALORIE_FLOOR_KCAL * 1.15:
            S = max(S, 1); reasons["S"].append(f"energy {s.total_kcal:.0f} kcal close to floor")
        n_items = sum(len(m_.get("items", [])) for m_ in (s.content.get("diet", s.content)).get("meals", [])) or 1
        if s.unverified_foods and len(s.unverified_foods) / n_items > 0.5:
            S = max(S, 1); reasons["S"].append("most foods are not in the versioned nutrition table (allergens cannot be checked)")
    if s.kind == CandidateKind.FOOD_ANALYSIS:
        if s.allergen_hits:
            S = max(S, 1); reasons["S"].append("possible allergen exposure in the logged food (safety notice shown)")
    for fl in s.coach_flags:
        sev = int(fl.get("severity", 0))
        if sev > S:
            S = sev; reasons["S"].append(f"coach flag {fl.get('code')} severity {sev}")
    S = _clamp(S, 0, 3)

    # U — uncertainty of the evidence (0-3)
    U = 0
    if s.confidence is not None and s.confidence < 0.5:
        U += 1; reasons["U"].append(f"confidence {s.confidence:.2f} < 0.5")
    if s.unverified_foods:
        U += 1; reasons["U"].append("nutrient values partly unverified")
    if s.kind in (CandidateKind.EXERCISE, CandidateKind.INTEGRATED):
        if s.readiness_result is None:
            U += 2; reasons["U"].append("no readiness assessment")
        elif s.readiness_age_hours is not None and s.readiness_age_hours > 24:
            U += 1; reasons["U"].append(f"readiness assessment {s.readiness_age_hours:.0f} h old")
    if not s.evidence_complete:
        U += 1; reasons["U"].append("evidence incomplete")
    if s.content.get("range_widened"):
        U -= 1; reasons["U"].append("uncertainty range widened and disclosed (−1)")
    U = _clamp(U, 0, 3)

    # V — vulnerability recorded in the authorised profile (0-2), counted where it is relevant to the content
    V = 0
    dietary = s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED, CandidateKind.FOOD_ANALYSIS)
    physical = s.kind in (CandidateKind.EXERCISE, CandidateKind.INTEGRATED)
    if s.allergies and dietary:
        V += 1; reasons["V"].append("allergies recorded")
    if s.physical_limits and physical:
        V += 1; reasons["V"].append("physical limits recorded")
    if s.readiness_result == ReadinessResult.RECOVERY.value and physical:
        V += 1; reasons["V"].append("Recovery readiness")
    V = _clamp(V, 0, 2)

    # P — proximity to a policy boundary without triggering it (0-2)
    P = 0
    if s.kind in (CandidateKind.EXERCISE, CandidateKind.INTEGRATED):
        if s.available_time_min and s.total_duration_min >= 0.9 * s.available_time_min:
            P += 1; reasons["P"].append("duration within 10% of available time")
        if s.readiness_result == ReadinessResult.REDUCED.value and s.max_intensity_rank >= 1:
            P += 1; reasons["P"].append("Reduced readiness with light-moderate or higher intensity")
        if s.readiness_result == ReadinessResult.RECOVERY.value and s.max_intensity_rank == 0 and s.total_duration_min > 20:
            P += 1; reasons["P"].append("Recovery day with > 20 min of activity")
    if s.kind in (CandidateKind.DIET, CandidateKind.INTEGRATED) and s.total_kcal:
        if CALORIE_FLOOR_KCAL <= s.total_kcal < CALORIE_FLOOR_KCAL * 1.10:
            P += 1; reasons["P"].append("energy within 10% above the floor")
    if s.pain_reported is not None and 4 <= s.pain_reported < 7:
        P += 1; reasons["P"].append(f"pain {s.pain_reported}/10 close to the critical threshold")
    P = _clamp(P, 0, 2)

    # B — behavioural pattern (0-2)
    B = 0
    if s.non_completion_count >= 3:
        B += 1; reasons["B"].append(f"{s.non_completion_count} recent non-completions (≥ 3)")
    if s.restriction_request_count >= 2:
        B += 1; reasons["B"].append(f"{s.restriction_request_count} restriction/compensation requests (≥ 2)")
    B = _clamp(B, 0, 2)

    return RiskScore(S, U, V, P, B, reasons)


def classify(score: RiskScore, critical_rule_triggered: bool, thresholds: Dict[str, Any]) -> RiskLevel:
    """First matching rule wins (UC10 scoring policy)."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    R = score.R
    if critical_rule_triggered or R >= t["critical_min"]:
        return RiskLevel.CRITICAL
    if score.S >= t["severity_high"] or R >= t["high_min"]:
        return RiskLevel.HIGH
    if R >= t["medium_min"]:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
