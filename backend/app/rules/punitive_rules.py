"""AR-03 / UC04 3a, UC06 note: plans are never made stricter to punish or compensate."""
from typing import List, Tuple

from .text_patterns import PUNITIVE_OUTPUT_PATTERNS, PUNITIVE_REQUEST_PATTERNS, describe_hits, match_any

CALORIE_FLOOR_KCAL = 1200       # prototype floor for a personalised daily plan
MIN_MEALS_PER_DAY = 3


def detect_punitive_request(text: str) -> Tuple[bool, str]:
    hits = match_any(text or "", PUNITIVE_REQUEST_PATTERNS)
    return (bool(hits), describe_hits(hits))


def detect_punitive_output(text: str) -> Tuple[bool, str]:
    """Directive punitive content in a plan or explanation (not the user's request)."""
    hits = match_any(text or "", PUNITIVE_OUTPUT_PATTERNS, negation_aware=True)
    return (bool(hits), describe_hits(hits))


def check_plan_not_punitive(total_kcal: float, meals_count: int, previous_total_kcal: float = None) -> List[str]:
    """Return reasons the plan looks punitive/restrictive (empty = fine)."""
    reasons = []
    if total_kcal and total_kcal < CALORIE_FLOOR_KCAL:
        reasons.append(f"daily energy {total_kcal:.0f} kcal below prototype floor {CALORIE_FLOOR_KCAL} kcal")
    if meals_count and meals_count < MIN_MEALS_PER_DAY:
        reasons.append(f"only {meals_count} meal(s) planned (minimum {MIN_MEALS_PER_DAY})")
    if previous_total_kcal and total_kcal and total_kcal < previous_total_kcal * 0.8:
        reasons.append("revision cuts energy by more than 20% versus the previous version")
    return reasons
