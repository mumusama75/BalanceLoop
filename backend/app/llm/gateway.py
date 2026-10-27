"""LLMGateway — the only way agents reach a language model (class diagram «interface» LLMGateway).

The gateway returns *structured* objects only: every method sends a JSON schema and
validates the reply. Anything that fails validation raises ``LLMUnavailable`` so the
calling agent follows the documented degradation path (e.g. UC05 4b, UC06 4b, UC09 5b, UC10 4a).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type, TypeVar

from pydantic import BaseModel

from ..domain.schemas import (AdaptationProposal, BarrierProposal, ConflictClassification, DietPlanDraft,
                              DietRevisionDraft, ExercisePlanDraft, FoodInterpretation, ProfileDraft,
                              ReadinessProposal, RecoveryInterpretation, RevisionInstruction)
from . import prompts

T = TypeVar("T", bound=BaseModel)

SENSITIVE_KEYS = {"user_id", "display_name", "email", "phone", "founder_id"}


class LLMUnavailable(Exception):
    """The model could not be reached or did not return a usable structured reply."""


def deidentify(obj: Any) -> Any:
    """Strip direct identifiers before anything leaves the system (CloudLLMClient: de-identified input only)."""
    if isinstance(obj, dict):
        return {k: deidentify(v) for k, v in obj.items() if k not in SENSITIVE_KEYS}
    if isinstance(obj, list):
        return [deidentify(v) for v in obj]
    return obj


class LLMGateway(ABC):
    model_version: str = "unknown"
    last_meta: Dict[str, Any] = {}

    @abstractmethod
    def complete(self, system: str, user: str, schema: Type[T]) -> T:
        """Send one structured request; return a validated *schema* instance or raise LLMUnavailable."""

    # ---- helpers
    def _call(self, system: str, payload: Dict[str, Any], schema: Type[T]) -> T:
        return self.complete(system, json.dumps(deidentify(payload), ensure_ascii=False, default=str), schema)

    # ---- UC01
    def interpret_constraints(self, profile: Dict[str, Any], free_text: str) -> ProfileDraft:
        return self._call(prompts.INTERPRET_CONSTRAINTS, {"profile": profile, "free_text": free_text}, ProfileDraft)

    # ---- UC02
    def identify_food(self, text: str, context: Dict[str, Any]) -> FoodInterpretation:
        return self._call(prompts.IDENTIFY_FOOD, {"input": text, **context}, FoodInterpretation)

    # ---- UC03
    def generate_diet_candidate(self, context: Dict[str, Any]) -> DietPlanDraft:
        return self._call(prompts.GENERATE_DIET, context, DietPlanDraft)

    # ---- UC04
    def interpret_feedback(self, feedback: Dict[str, Any], plan: Dict[str, Any]) -> BarrierProposal:
        return self._call(prompts.INTERPRET_FEEDBACK, {"feedback": feedback, "current_plan": plan}, BarrierProposal)

    def propose_minimal_change(self, context: Dict[str, Any], strategy: str) -> DietRevisionDraft:
        return self._call(prompts.PROPOSE_MINIMAL_CHANGE, {**context, "strategy": strategy}, DietRevisionDraft)

    # ---- UC05
    def assess_readiness(self, checkin: Dict[str, Any], context: Dict[str, Any]) -> ReadinessProposal:
        return self._call(prompts.ASSESS_READINESS, {"checkin": checkin, **context}, ReadinessProposal)

    # ---- UC06
    def generate_exercise_candidate(self, context: Dict[str, Any]) -> ExercisePlanDraft:
        return self._call(prompts.GENERATE_EXERCISE, context, ExercisePlanDraft)

    # ---- UC07
    def interpret_recovery_notes(self, notes: str, context: Dict[str, Any]) -> RecoveryInterpretation:
        return self._call(prompts.INTERPRET_RECOVERY, {"notes": notes, **context}, RecoveryInterpretation)

    # ---- UC08
    def propose_adaptations(self, feedback: List[Dict[str, Any]], readiness: Dict[str, Any], plan: Dict[str, Any]) -> AdaptationProposal:
        return self._call(prompts.PROPOSE_ADAPTATIONS, {"feedback": feedback, "readiness": readiness, "plan": plan}, AdaptationProposal)

    # ---- UC09
    def classify_conflict(self, conflict: Dict[str, Any], context: Dict[str, Any]) -> ConflictClassification:
        return self._call(prompts.CLASSIFY_CONFLICT, {"conflict": conflict, **context}, ConflictClassification)

    # ---- UC10
    def draft_revision_instructions(self, rules: List[Dict[str, Any]], candidate: Dict[str, Any]) -> RevisionInstruction:
        return self._call(prompts.DRAFT_REVISION, {"triggered_rules": rules, "candidate": candidate}, RevisionInstruction)
