"""Small shared types for agent ↔ orchestrator communication."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional

from ..db import models as m
from ..domain.enums import OutcomeStatus


@dataclass
class Halt:
    """A Coach could not deliver a candidate; explains why and what the user should do."""
    status: OutcomeStatus
    message: str
    content: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def next_version(repo, user_id: str, kind: str) -> int:
    prev = repo.latest_candidate(user_id, kind)
    return (prev.version + 1) if prev else 1


def profile_context(profile: Optional[m.UserProfile]) -> Dict[str, Any]:
    if profile is None:
        return {}
    return {"version": profile.version, "goals": profile.goals, "dietary_preferences": profile.dietary_preferences,
            "allergy_status": profile.allergy_status, "allergies": profile.allergies, "physical_limits": profile.physical_limits,
            "available_time_min": profile.available_time_min, "equipment": profile.equipment, "budget_level": profile.budget_level,
            "cultural_preferences": profile.cultural_preferences, "schedule_notes": profile.schedule_notes,
            "cooking_skill": profile.cooking_skill}


def candidate_view(c: m.PlanCandidate) -> Dict[str, Any]:
    """Uniform JSON view of a candidate for API replies."""
    return {"candidate_id": c.id, "kind": c.kind, "version": c.version, "status": c.status, "released": c.released,
            "plan_date": c.plan_date.isoformat() if c.plan_date else None, "profile_version": c.profile_version,
            "previous_version_id": c.previous_version_id, "rationale": c.rationale, "risk_flags": c.risk_flags,
            "model_version": c.model_version, "created_at": c.created_at.isoformat() if c.created_at else None,
            "change_explanation": c.change_explanation, "repair_count": c.repair_count, **(c.content or {})}
