"""Agent base class (class diagram «abstract» Agent) and the per-request context shared by all agents.

Every agent follows the perceive → reason → act → explain cycle. Agents reach storage only
through ``Repository`` and the language model only through ``LLMGateway`` (Fig. 4).
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..config import Settings
from ..domain.enums import AgentRole
from ..external.nutrition_local import LocalNutritionSource
from ..llm.gateway import LLMGateway
from ..llm.telemetry import TracedGateway
from ..repository.versioned_store import VersionedRecordStore
from ..services.trace import Trace


@dataclass
class AgentContext:
    """Dependencies and identity of one user request."""
    repo: VersionedRecordStore
    llm: LLMGateway
    nutrition: LocalNutritionSource
    settings: Settings
    trace: Trace
    request_id: str
    user_id: Optional[str]
    scratch: Dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    role: AgentRole
    agent_version: str = "1.0"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.agent_id = f"{self.role.value.lower()}-{self.agent_version}"
        self._last_explanation: str = ""
        self._traced_llm = TracedGateway(ctx.llm, ctx.trace, self.role.value)

    # ---- shared infrastructure
    @property
    def repo(self) -> VersionedRecordStore:
        return self.ctx.repo

    @property
    def llm(self) -> TracedGateway:
        return self._traced_llm

    @property
    def model_version(self) -> str:
        return self.ctx.llm.model_version

    def trace(self, step: str, summary: str, *, llm_used: bool = False, detail: Optional[Dict[str, Any]] = None):
        return self.ctx.trace.add(self.role.value, step, summary, llm_used=llm_used,
                                  model_version=self.model_version if llm_used else None, detail=detail)

    def audit(self, action: str, *, decision: Optional[str] = None, versions: Optional[Dict[str, Any]] = None,
              payload: Optional[Dict[str, Any]] = None) -> str:
        v = {"agent": self.agent_id, "model_version": self.model_version, **(versions or {})}
        return self.repo.append_audit(self.ctx.request_id, self.ctx.user_id, self.role.value, action,
                                      decision=decision, versions=v, payload=payload)

    # ---- the agent cycle (hooks; concrete agents compose them inside their use-case methods)
    def perceive(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Load the authorised context needed for the task. Default: pass-through."""
        return dict(input)

    def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Draft / interpret (LLM) and check (rules). Default: no-op."""
        return dict(context)

    def act(self, decision: Dict[str, Any]) -> Any:
        """Persist, submit or notify. Default: return the decision."""
        return decision

    def explain(self) -> str:
        return self._last_explanation
