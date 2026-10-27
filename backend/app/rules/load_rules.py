"""UC08 load rules: a revision may not introduce an unsupported increase in load (AR-05)."""
from typing import Dict, List, Tuple

from ..domain.enums import INTENSITY_RANK, AdaptationAction, Intensity

MAX_DURATION_GROWTH = 1.10      # total minutes may grow at most 10 %
REPEATED_NON_COMPLETION = 2     # >= 2 skipped/partial -> simplify only


def total_minutes(activities: List[Dict]) -> int:
    return sum(int(a.get("duration_min", 0)) for a in activities if not a.get("paused"))


def max_rank(activities: List[Dict]) -> int:
    ranks = [INTENSITY_RANK[Intensity(a["intensity"])] for a in activities if not a.get("paused")]
    return max(ranks) if ranks else -1


def check_load_increase(old_activities: List[Dict], new_activities: List[Dict]) -> Tuple[bool, List[str]]:
    reasons = []
    old_t, new_t = total_minutes(old_activities), total_minutes(new_activities)
    if old_t and new_t > old_t * MAX_DURATION_GROWTH:
        reasons.append(f"total duration {new_t} min exceeds {old_t} min × {MAX_DURATION_GROWTH:.2f}")
    if max_rank(new_activities) > max_rank(old_activities):
        reasons.append("maximum intensity increased")
    return (not reasons, reasons)


def allowed_actions(non_completion_count: int, pain_reported: bool) -> List[AdaptationAction]:
    if pain_reported:
        return [AdaptationAction.PAUSE, AdaptationAction.REPLACE]
    if non_completion_count >= REPEATED_NON_COMPLETION:
        return [AdaptationAction.REDUCE, AdaptationAction.REPLACE, AdaptationAction.PAUSE]
    return list(AdaptationAction)


def conservative_action(non_completion_count: int, pain_reported: bool) -> AdaptationAction:
    if pain_reported:
        return AdaptationAction.PAUSE
    return AdaptationAction.REDUCE if non_completion_count else AdaptationAction.MAINTAIN
