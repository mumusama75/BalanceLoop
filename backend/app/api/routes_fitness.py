"""UC05 readiness, UC06 exercise plan, UC07 activity feedback, UC08 adaptation."""
from fastapi import APIRouter, Depends

from ..agents.orchestrator import Orchestrator
from ..domain.schemas import ActivityFeedbackIn, AdaptRequestIn, ExercisePlanRequestIn, OperationResult, ReadinessCheckInIn
from ..repository.versioned_store import VersionedRecordStore
from .deps import current_user, get_orchestrator, get_repo

router = APIRouter(prefix="/api", tags=["fitness (UC05-UC08)"])


@router.post("/readiness/checkins", response_model=OperationResult)
def checkin(data: ReadinessCheckInIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.submit_checkin(data)


@router.get("/readiness/latest")
def latest(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    a = repo.reload_latest_readiness(user.id, usable_only=False)
    return Orchestrator._assessment_view(a) if a else {"assessment": None}


@router.get("/readiness/history")
def history(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    """What the app already knows before a check-in: recorded activity (48 h) and the last assessments."""
    from ..agents.fitness_coach import FitnessCoach
    records = repo.recent_activity_records(user.id, hours=48)
    return {"recorded_activity": records, "summary": FitnessCoach.summarise_history(records),
            "previous": [Orchestrator._assessment_view(a)["assessment"] for a in repo.recent_assessments(user.id)]}


@router.post("/exercise/plans", response_model=OperationResult)
def request_exercise_plan(data: ExercisePlanRequestIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.request_exercise_plan(data)


@router.post("/exercise/activities/{item_id}/feedback", response_model=OperationResult)
def activity_feedback(item_id: str, data: ActivityFeedbackIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.submit_activity_feedback(item_id, data)


@router.post("/exercise/plans/adapt", response_model=OperationResult)
def adapt(data: AdaptRequestIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.request_plan_adaptation(data)


@router.get("/exercise/feedback")
def feedback_list(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    plan = repo.current_released(user.id, "exercise")
    if not plan:
        return []
    return [{"id": f.id, "activity_item_id": f.activity_item_id, "completion": f.completion, "exertion": f.exertion, "pain": f.pain,
             "fatigue": f.fatigue, "warning_signs": f.warning_signs, "progression_hold": f.progression_hold, "status": f.status,
             "created_at": f.created_at.isoformat()} for f in repo.feedback_for_candidate(plan.id)]
