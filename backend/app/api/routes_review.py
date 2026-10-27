"""UC09 integrated daily plan, UC10 review cases & traces (user-visible part)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..agents.orchestrator import Orchestrator
from ..domain.schemas import DailyPlanRequestIn, OperationResult
from ..repository.versioned_store import VersionedRecordStore
from .deps import current_user, get_orchestrator, get_repo

router = APIRouter(prefix="/api", tags=["daily plan & review (UC09-UC10)"])


@router.post("/daily-plan", response_model=OperationResult)
def daily_plan(data: DailyPlanRequestIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.request_daily_plan(data)


def case_view(c, repo) -> dict:
    return {"id": c.id, "request_id": c.request_id, "user_id": c.user_id, "candidate_id": c.candidate_id, "candidate_version": c.candidate_version,
            "kind": c.kind, "state": c.state, "repair_count": c.repair_count, "final_status": c.final_status,
            "created_at": c.created_at.isoformat(), "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "decisions": [{"id": d.id, "decision": d.decision, "risk_score": d.risk_score, "risk_level": d.risk_level,
                           "score_breakdown": d.score_breakdown, "triggered_rules": d.triggered_rules, "policy_version": d.policy_version,
                           "rationale": d.rationale, "revision_instructions": d.revision_instructions, "candidate_version": d.candidate_version,
                           "created_at": d.created_at.isoformat()} for d in c.decisions]}


@router.get("/review/cases")
def my_cases(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [case_view(c, repo) for c in repo.list_cases(user.id)]


@router.get("/review/cases/{case_id}")
def one_case(case_id: str, user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    c = repo.get_case(case_id)
    if c is None or (c.user_id != user.id and user.role != "founder"):
        raise HTTPException(404, "case not found")
    return case_view(c, repo)


@router.get("/review/requests/{request_id}/trace")
def trace(request_id: str, user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    steps = repo.load_trace(request_id)
    if steps and steps[0].user_id not in (user.id, None) and user.role != "founder":
        raise HTTPException(404, "trace not found")
    return [{"seq": s.seq, "agent": s.agent, "step": s.step, "llm_used": s.llm_used, "model_version": s.model_version,
             "summary": s.summary, "detail": s.detail, "at": s.created_at.isoformat()} for s in steps]
