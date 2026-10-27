"""UC09 reconciliation: fixed rules decide whether a conflict exists (AR-06)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from ..domain.enums import INTENSITY_RANK, AgentRole, ConflictType, Intensity, ReadinessResult

MIN_MEAL_TO_SESSION_GAP_MIN = 30
LOW_ENERGY_ACTIVE_DAY_KCAL = 1400
ACTIVE_DAY_MINUTES = 45


@dataclass
class Conflict:
    type: ConflictType
    description: str
    responsible_agent: AgentRole


def _minutes(hhmm: str) -> Optional[int]:
    try:
        t = datetime.strptime(hhmm.strip(), "%H:%M")
        return t.hour * 60 + t.minute
    except Exception:
        return None


def detect_conflicts(diet: Dict, exercise: Dict, readiness_result: Optional[str], available_time_min: Optional[int],
                     diet_profile_version: Optional[int], exercise_profile_version: Optional[int]) -> List[Conflict]:
    conflicts: List[Conflict] = []

    # Profile version consistency (UC09 step 3 / ext. 3a) — the Coach with the older version regenerates.
    if diet_profile_version is not None and exercise_profile_version is not None and diet_profile_version != exercise_profile_version:
        older = AgentRole.NUTRITION_COACH if diet_profile_version < exercise_profile_version else AgentRole.FITNESS_COACH
        conflicts.append(Conflict(ConflictType.PROFILE_VERSION,
                                  f"diet candidate uses profile v{diet_profile_version}, exercise candidate v{exercise_profile_version}",
                                  older))
        return conflicts  # nothing else is meaningful until both use the same profile

    activities = [a for a in exercise.get("activities", []) if not a.get("paused")]
    session_start = _minutes(exercise.get("session_time", "") or "")
    total_min = sum(int(a.get("duration_min", 0)) for a in activities)

    # timing: a meal within 30 min before the session start
    if session_start is not None:
        for meal in diet.get("meals", []):
            mt = _minutes(meal.get("time", "") or "")
            if mt is not None and 0 <= session_start - mt < MIN_MEAL_TO_SESSION_GAP_MIN:
                conflicts.append(Conflict(ConflictType.TIMING,
                                          f"{meal.get('name')} at {meal.get('time')} is less than {MIN_MEAL_TO_SESSION_GAP_MIN} min before the {exercise.get('session_time')} session",
                                          AgentRole.FITNESS_COACH))
                break

    # recovery: exercise ignores a Recovery result
    if readiness_result == ReadinessResult.RECOVERY.value:
        for a in activities:
            if INTENSITY_RANK[Intensity(a["intensity"])] > INTENSITY_RANK[Intensity.LIGHT]:
                conflicts.append(Conflict(ConflictType.RECOVERY,
                                          f"readiness is Recovery but '{a['name']}' is {a['intensity']} intensity",
                                          AgentRole.FITNESS_COACH))
                break

    # workload: total session time exceeds the user's available time
    if available_time_min and total_min > available_time_min:
        conflicts.append(Conflict(ConflictType.WORKLOAD,
                                  f"planned activity {total_min} min exceeds available time {available_time_min} min",
                                  AgentRole.FITNESS_COACH))

    # nutrition: active day with clearly insufficient energy
    total_kcal = float(diet.get("total_kcal") or 0)
    if total_min >= ACTIVE_DAY_MINUTES and total_kcal and total_kcal < LOW_ENERGY_ACTIVE_DAY_KCAL:
        conflicts.append(Conflict(ConflictType.NUTRITION,
                                  f"{total_kcal:.0f} kcal planned for a day with {total_min} min of activity (< {LOW_ENERGY_ACTIVE_DAY_KCAL} kcal)",
                                  AgentRole.NUTRITION_COACH))
    return conflicts
