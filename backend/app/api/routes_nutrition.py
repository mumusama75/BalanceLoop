"""UC02 food intake, UC03 diet plan, UC04 diet feedback."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends

from ..agents.orchestrator import Orchestrator
from ..domain.schemas import DietFeedbackIn, DietPlanRequestIn, FoodClarifyIn, FoodEntryIn, OperationResult
from ..repository.versioned_store import VersionedRecordStore
from .deps import current_user, get_orchestrator, get_repo

router = APIRouter(prefix="/api", tags=["nutrition (UC02-UC04)"])


@router.post("/food/entries", response_model=OperationResult)
def record_meal(data: FoodEntryIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.record_meal(data)


@router.post("/food/entries/{entry_id}/clarify", response_model=OperationResult)
def clarify_meal(entry_id: str, data: FoodClarifyIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.clarify_meal(entry_id, data)


@router.get("/food/entries")
def list_entries(day: Optional[date] = None, user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [Orchestrator._entry_view(e)["entry"] for e in repo.list_food_entries(user.id, day)]


@router.post("/diet/plans", response_model=OperationResult)
def request_diet_plan(data: DietPlanRequestIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.request_diet_plan(data)


@router.post("/diet/feedback", response_model=OperationResult)
def diet_feedback(data: DietFeedbackIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.submit_diet_feedback(data)


@router.get("/nutrition/foods")
def foods(q: Optional[str] = None, orch: Orchestrator = Depends(get_orchestrator)):
    ns = orch.ctx.nutrition
    items = ns.foods if not q else [f for f in ns.foods if q.lower() in f["name"].lower() or any(q.lower() in a for a in f["aliases"])]
    return {"version": ns.version, "source": ns.source_name, "foods": [{"id": f["id"], "name": f["name"], "category": f["category"],
                                                                        "per_100g": f["per_100g"], "allergens": f["allergens"]} for f in items[:100]]}
