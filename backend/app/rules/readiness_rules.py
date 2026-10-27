"""UC05 readiness rules: fixed rules decide Ready / Reduced / Recovery.

Missing or contradictory information is never treated as Ready (AR-04).
Prototype thresholds — not clinical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..domain.enums import ReadinessResult

RULE_VERSION = "readiness-rules-1.0"
REQUIRED_FIELDS = ["sleep_quality", "fatigue", "soreness", "pain", "available_time_min"]
# "recent_activity" is the user's own report of activity the app has no record of (e.g. today, before the check-in);
# activity the app already recorded (UC07 feedback) is loaded from the repository and passed as has_recorded_activity.

PAIN_RECOVERY_THRESHOLD = 4      # pain >= 4/10 -> Recovery
FATIGUE_REDUCED_THRESHOLD = 7    # fatigue >= 7/10 -> Reduced
SLEEP_REDUCED_THRESHOLD = 2      # sleep quality <= 2/5 -> Reduced
SORENESS_REDUCED_THRESHOLD = 6   # soreness >= 6/10 -> Reduced


@dataclass
class ReadinessDecision:
    result: Optional[ReadinessResult]
    restrictions: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    clarification_fields: List[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification_fields)


def validate_checkin(checkin: Dict[str, Any], has_recorded_activity: bool = False) -> List[str]:
    """Return the fields that are missing or contradictory (empty list = valid)."""
    problems: List[str] = []
    for f in REQUIRED_FIELDS:
        v = checkin.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append(f)
    pain = checkin.get("pain")
    if pain is not None and pain > 0 and checkin.get("pain_affects_activity") is None and pain < PAIN_RECOVERY_THRESHOLD:
        problems.append("pain_affects_activity")
    recent = (checkin.get("recent_activity") or "").strip().lower()
    soreness = checkin.get("soreness")
    if soreness is not None and soreness >= 8 and not has_recorded_activity and recent in {"", "none", "no", "nothing", "rest"}:
        problems.append("soreness (very high soreness but no activity recorded or reported in the last 48 h — please confirm)")
    return problems


def decide(checkin: Dict[str, Any], llm_pain_affects: Optional[bool], llm_capacity_reduced: Optional[bool],
           llm_restrictions: List[str], active_restrictions: List[str], has_recorded_activity: bool = False) -> ReadinessDecision:
    """Apply the fixed rules. LLM-derived flags only *add* evidence; they can never make a result safer."""
    problems = validate_checkin(checkin, has_recorded_activity)
    if problems:
        return ReadinessDecision(result=None, clarification_fields=problems,
                                 evidence=["Information missing or contradictory; not treated as Ready."])

    pain = checkin["pain"]
    evidence: List[str] = []
    restrictions: List[str] = list(active_restrictions or [])

    pain_affects = bool(llm_pain_affects) or bool(checkin.get("pain_affects_activity"))
    if pain >= PAIN_RECOVERY_THRESHOLD or (pain > 0 and pain_affects) or active_restrictions:
        if pain >= PAIN_RECOVERY_THRESHOLD:
            evidence.append(f"Pain {pain}/10 ≥ {PAIN_RECOVERY_THRESHOLD}: recovery required.")
        elif pain > 0 and pain_affects:
            evidence.append(f"Pain {pain}/10 reported as affecting safe activity.")
        if active_restrictions:
            evidence.append(f"Active recovery restriction(s): {', '.join(active_restrictions)}.")
        restrictions = sorted(set(restrictions + ["no loaded or impact activity", "light mobility only"] + list(llm_restrictions or [])))
        return ReadinessDecision(ReadinessResult.RECOVERY, restrictions, evidence)

    reduced_reasons = []
    if checkin["fatigue"] >= FATIGUE_REDUCED_THRESHOLD:
        reduced_reasons.append(f"fatigue {checkin['fatigue']}/10 ≥ {FATIGUE_REDUCED_THRESHOLD}")
    if checkin["sleep_quality"] <= SLEEP_REDUCED_THRESHOLD:
        reduced_reasons.append(f"sleep quality {checkin['sleep_quality']}/5 ≤ {SLEEP_REDUCED_THRESHOLD}")
    if checkin["soreness"] >= SORENESS_REDUCED_THRESHOLD:
        reduced_reasons.append(f"soreness {checkin['soreness']}/10 ≥ {SORENESS_REDUCED_THRESHOLD}")
    if llm_capacity_reduced:
        reduced_reasons.append("check-in text indicates reduced capacity")
    if reduced_reasons:
        evidence.append("Reduced capacity: " + "; ".join(reduced_reasons) + ".")
        return ReadinessDecision(ReadinessResult.REDUCED, ["keep intensity light", "shorten session"], evidence)

    evidence.append("No pain affecting activity, fatigue, sleep and soreness within normal range.")
    return ReadinessDecision(ReadinessResult.READY, [], evidence)
