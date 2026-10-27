"""Build the ``ReviewSubject`` the Safety Supervisor reviews, from a stored candidate and the authorised context."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..db import models as m
from ..domain.enums import INTENSITY_RANK, CandidateKind, Intensity
from ..rules.hard_rules import ReviewSubject
from ..util import utcnow
from .base import AgentContext


def _texts(obj: Any, out: List[str]):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _texts(v, out)


def _exercise_features(content: Dict[str, Any], subject: ReviewSubject):
    acts = [a for a in content.get("activities", []) if not a.get("paused")]
    subject.total_duration_min = sum(int(a.get("duration_min", 0)) for a in acts)
    ranks = [INTENSITY_RANK[Intensity(a["intensity"])] for a in acts]
    if ranks:
        subject.max_intensity = [k.value for k, v in INTENSITY_RANK.items() if v == max(ranks)][0]


def _diet_features(content: Dict[str, Any], subject: ReviewSubject, ctx: AgentContext, allergies: List[str]):
    subject.total_kcal = float(content.get("total_kcal") or 0) or None
    subject.meals_count = len(content.get("meals", []))
    foods = []
    for meal in content.get("meals", []):
        for it in meal.get("items", []):
            f = ctx.nutrition.lookup(it.get("food", ""))
            if f:
                foods.append(f)
            else:
                subject.unverified_foods.append(it.get("food", "?"))
    subject.allergen_hits = ctx.nutrition.allergen_conflicts(foods, allergies)
    if content.get("previous_total_kcal"):
        subject.previous_total_kcal = float(content["previous_total_kcal"])


EXPLANATORY_KEYS = {"rationale", "change_explanation", "constraints_explanation", "difficulty", "uncertainties",
                    "adaptation_summary", "confidence_basis", "source_input", "diet_candidate_id", "exercise_candidate_id",
                    "notes", "changed_elements", "summary_text"}  # notes are reassurance/prep hints; the quantitative rules guard the plan itself


def directive_text(content: Dict[str, Any]) -> str:
    """Only the parts of a plan that tell the user what to do."""
    out: List[str] = []
    _texts({k: v for k, v in content.items() if k not in EXPLANATORY_KEYS}, out)
    return "\n".join(out)


def build_subject(candidate: m.PlanCandidate, ctx: AgentContext, *, user_input_text: str = "") -> ReviewSubject:
    profile = ctx.repo.reload_profile(candidate.user_id)
    kind = CandidateKind(candidate.kind)
    content = candidate.content or {}
    texts: List[str] = []
    _texts({k: v for k, v in content.items() if k not in ("source_input", "diet_candidate_id", "exercise_candidate_id")}, texts)

    subject = ReviewSubject(kind=kind, candidate_id=candidate.id, version=candidate.version,
                            profile_version=candidate.profile_version,
                            current_profile_version=profile.version if profile else None,
                            content=content, output_text="\n".join(texts), directive_text=directive_text(content),
                            user_input_text=user_input_text or content.get("source_input", "") or "",
                            allergies=list(profile.allergies) if profile else [],
                            allergy_status=profile.allergy_status if profile else "unknown",
                            physical_limits=list(profile.physical_limits) if profile else [],
                            evidence_complete=bool(content) and candidate.model_version is not None,
                            model_version=candidate.model_version,
                            available_time_min=profile.available_time_min if profile else None,
                            confidence=content.get("confidence"),
                            coach_flags=list(candidate.risk_flags or []))

    readiness = ctx.repo.reload_latest_readiness(candidate.user_id, usable_only=True)
    if readiness:
        subject.readiness_result = readiness.result
        subject.readiness_age_hours = (utcnow() - readiness.created_at).total_seconds() / 3600.0

    if kind == CandidateKind.EXERCISE:
        _exercise_features(content, subject)
    elif kind == CandidateKind.DIET:
        _diet_features(content, subject, ctx, subject.allergies)
    elif kind == CandidateKind.INTEGRATED:
        _exercise_features(content.get("exercise", {}), subject)
        _diet_features(content.get("diet", {}), subject, ctx, subject.allergies)
    elif kind == CandidateKind.FOOD_ANALYSIS:
        foods = [ctx.nutrition.lookup(i.get("name", "")) for i in content.get("items", [])]
        subject.allergen_hits = ctx.nutrition.allergen_conflicts([f for f in foods if f], subject.allergies)
        subject.unverified_foods = [i.get("name", "?") for i, f in zip(content.get("items", []), foods) if not f]

    subject.non_completion_count = ctx.repo.non_completion_count(candidate.user_id)
    subject.restriction_request_count = ctx.repo.restriction_request_count(candidate.user_id)
    if content.get("pain_reported") is not None:
        subject.pain_reported = int(content["pain_reported"])
    return subject
