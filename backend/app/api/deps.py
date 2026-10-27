"""FastAPI dependencies: DB session, LLM gateway singleton, per-request AgentContext and Orchestrator."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..agents.base import AgentContext
from ..agents.orchestrator import Orchestrator
from ..config import Settings, get_settings
from ..db.database import get_db
from ..external.nutrition_local import get_nutrition_source
from ..llm.cloud_client import CloudLLMClient
from ..llm.gateway import LLMGateway
from ..llm.mock_client import MockLLMClient
from ..repository.versioned_store import VersionedRecordStore
from ..services.trace import Trace
from ..util import new_id


@lru_cache
def get_llm() -> LLMGateway:
    s = get_settings()
    if s.llm_provider.lower() == "cloud" and s.llm_api_key:
        return CloudLLMClient(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_seconds)
    return MockLLMClient()


def get_repo(db: Session = Depends(get_db)) -> VersionedRecordStore:
    return VersionedRecordStore(db)


def current_user(repo: VersionedRecordStore = Depends(get_repo), x_user_id: Optional[str] = Header(default=None, alias="X-User-Id")):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required (demo login)")
    user = repo.get_user(x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return user


def founder_user(user=Depends(current_user)):
    if user.role != "founder":
        raise HTTPException(status_code=403, detail="Founder role required")
    return user


def get_ctx(repo: VersionedRecordStore = Depends(get_repo), user=Depends(current_user),
            settings: Settings = Depends(get_settings), llm: LLMGateway = Depends(get_llm)) -> AgentContext:
    request_id = new_id("req")
    return AgentContext(repo=repo, llm=llm, nutrition=get_nutrition_source(), settings=settings,
                        trace=Trace(request_id, user.id), request_id=request_id, user_id=user.id)


def get_orchestrator(ctx: AgentContext = Depends(get_ctx)) -> Orchestrator:
    return Orchestrator(ctx)
