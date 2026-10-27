"""Agent trace — records every pipeline step of one request (demo / explainability, AR-10)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..domain.schemas import TraceStep
from ..util import utcnow


class Trace:
    def __init__(self, request_id: str, user_id: Optional[str]):
        self.request_id = request_id
        self.user_id = user_id
        self.steps: List[TraceStep] = []

    def add(self, agent: str, step: str, summary: str, *, llm_used: bool = False,
            model_version: Optional[str] = None, detail: Optional[Dict[str, Any]] = None) -> TraceStep:
        ts = TraceStep(seq=len(self.steps) + 1, at=utcnow(), agent=str(agent), step=step, llm_used=llm_used,
                       model_version=model_version, summary=summary, detail=detail or {})
        self.steps.append(ts)
        return ts

    def as_list(self) -> List[TraceStep]:
        return list(self.steps)
