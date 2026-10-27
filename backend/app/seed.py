"""Demo seed: users, Founder, review policy v1.0 (active) and a draft policy for the fail-closed demo."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from .config import get_settings
from .db import models as m
from .rules.hard_rules import DEFAULT_POLICY_HARD_RULES
from .rules.risk_scoring import DEFAULT_THRESHOLDS
from .util import new_id, utcnow

DEMO_USERS = [
    {"id": "u_alex", "display_name": "Alex Chen", "role": "user"},     # fresh user: no profile yet (full UC01 demo)
    {"id": "u_sam", "display_name": "Sam Lee", "role": "user"},        # pre-filled profile + consent (fast path demo)
    {"id": "founder", "display_name": "Founder (Operator)", "role": "founder"},
]


def seed(db: Session, *, force: bool = False, demo_flow: bool = None) -> dict:
    created = {"users": 0, "policies": 0, "profiles": 0, "demo_flow": "skipped"}
    for u in DEMO_USERS:
        if db.get(m.User, u["id"]) is None:
            db.add(m.User(**u)); created["users"] += 1
    db.commit()

    if db.query(m.ReviewPolicy).filter(m.ReviewPolicy.version == "1.0").first() is None:
        db.add(m.ReviewPolicy(id=new_id("pol"), version="1.0", hard_rules=DEFAULT_POLICY_HARD_RULES, risk_thresholds=dict(DEFAULT_THRESHOLDS),
                              max_repairs=2, active=True, notes="Prototype policy — course thresholds, not clinical."))
        created["policies"] += 1
    if db.query(m.ReviewPolicy).filter(m.ReviewPolicy.version == "0.9-draft").first() is None:
        db.add(m.ReviewPolicy(id=new_id("pol"), version="0.9-draft", hard_rules=DEFAULT_POLICY_HARD_RULES, risk_thresholds=dict(DEFAULT_THRESHOLDS),
                              max_repairs=2, active=False, notes="Draft policy. Activating it demonstrates fail-closed (version mismatch with the required 1.0)."))
        created["policies"] += 1
    db.commit()

    # Sam: a complete, consented profile so the demo can jump straight to UC02–UC10
    if db.query(m.UserProfile).filter(m.UserProfile.user_id == "u_sam").first() is None:
        db.add(m.ConsentRecord(id=new_id("cons"), user_id="u_sam", scope="core",
                               agent_access=["Orchestrator", "NutritionCoach", "FitnessCoach", "SafetySupervisor"], profile_version=1))
        db.add(m.UserProfile(id=new_id("prof"), user_id="u_sam", version=1, status="Active",
                             goals=["build a low-intensity activity habit", "eat regular balanced meals"], dietary_preferences=["pescatarian"],
                             allergy_status="known", allergies=["peanuts"], physical_limits=["mild left knee discomfort on stairs"],
                             available_time_min=40, equipment=["resistance band", "yoga mat"], budget_level="medium",
                             cultural_preferences="East Asian home cooking", schedule_notes="Office hours 9-6, free after 17:30", cooking_skill="intermediate",
                             missing_fields=[], conflicts=[], is_current=True))
        created["profiles"] += 1
    db.commit()

    if demo_flow if demo_flow is not None else get_settings().seed_demo_flow:
        created["demo_flow"] = seed_demo_flow(db)
    return created


# ---------------------------------------------------------------- a scripted day for Sam (runs through the real agents)
_SHIFTABLE: List[Tuple[Any, str]] = [
    (m.ReadinessAssessment, "created_at"), (m.ReadinessCheckIn, "submitted_at"), (m.PlanCandidate, "created_at"),
    (m.ExercisePlanningRequest, "created_at"), (m.ActivityFeedback, "created_at"), (m.AdaptationDecision, "created_at"),
    (m.DietFeedback, "created_at"), (m.FoodEntry, "submitted_at"), (m.PlanConflict, "created_at"),
    (m.ReviewCase, "created_at"), (m.ReviewCase, "closed_at"), (m.ReviewDecision, "created_at"),
    (m.AuditRecord, "timestamp"), (m.AgentTrace, "created_at"), (m.Notification, "created_at"), (m.Incident, "created_at"),
]


def _shift_back(db: Session, since: datetime, days: int) -> None:
    """Move every record written since *since* back by *days* (so a flow run now reads as 'yesterday')."""
    delta = timedelta(days=days)
    for model, attr in _SHIFTABLE:
        col = getattr(model, attr)
        for row in db.query(model).filter(col >= since).all():
            setattr(row, attr, getattr(row, attr) - delta)
    db.commit()


def seed_demo_flow(db: Session) -> str:
    """Yesterday: check-in, exercise + diet plan, activity feedback, a meal.  Today: check-in, plans, meals, feedback.

    Everything goes through the Orchestrator with the offline MockLLMClient, so candidates, review cases,
    audit records and traces are all genuine — the demo user just does not have to type it all in.
    """
    from .agents.base import AgentContext
    from .agents.orchestrator import Orchestrator
    from .domain.enums import OutcomeStatus
    from .domain.schemas import (ActivityFeedbackIn, DietFeedbackIn, DietPlanRequestIn, ExercisePlanRequestIn, FoodClarifyIn,
                                 FoodEntryIn, ReadinessCheckInIn)
    from .external.nutrition_local import get_nutrition_source
    from .llm.mock_client import MockLLMClient
    from .repository.versioned_store import VersionedRecordStore
    from .services.trace import Trace

    repo = VersionedRecordStore(db)
    user = "u_sam"
    if repo.latest_candidate(user, "exercise") is not None:
        return "already present"
    llm = MockLLMClient()

    def orch() -> Orchestrator:
        rid = new_id("req")
        return Orchestrator(AgentContext(repo=repo, llm=llm, nutrition=get_nutrition_source(), settings=get_settings(),
                                         trace=Trace(rid, user), request_id=rid, user_id=user))

    def meal(text: str, answer: str = "a typical serving of each") -> None:
        """Log a meal; answer the Coach's portion question if it asks one (UC02 4a)."""
        res = orch().record_meal(FoodEntryIn(text=text))
        if res.status == OutcomeStatus.CLARIFICATION and res.content and res.content.get("entry"):
            orch().clarify_meal(res.content["entry"]["id"], FoodClarifyIn(answer=answer))

    today = date.today()
    yesterday = today - timedelta(days=1)

    # ---- yesterday
    started = utcnow()
    orch().submit_checkin(ReadinessCheckInIn(sleep_quality=4, fatigue=3, soreness=2, pain=0, pain_affects_activity=False,
                                             recent_activity="none", available_time_min=40, free_text="feeling fine"))
    orch().request_exercise_plan(ExercisePlanRequestIn(plan_date=yesterday))
    orch().request_diet_plan(DietPlanRequestIn(plan_date=yesterday))
    plan = repo.current_released(user, "exercise")
    if plan:
        for i, item in enumerate(plan.activities):
            orch().submit_activity_feedback(item.id, ActivityFeedbackIn(completion="completed" if i == 0 else "partial", exertion=5 if i == 0 else 4,
                                                                        pain=0, fatigue=4, recovery_notes="felt good, a bit tired afterwards" if i == 0 else "ran out of time"))
    meal("1 latte and 2 slices of whole wheat toast with 1 tbsp butter")
    meal("150 g grilled chicken breast with a bowl of rice and 100 g steamed broccoli")
    _shift_back(db, started, days=1)

    # ---- today
    orch().submit_checkin(ReadinessCheckInIn(sleep_quality=4, fatigue=3, soreness=3, pain=1, pain_affects_activity=False,
                                             recent_activity="cycled 10 min to the office", available_time_min=40,
                                             free_text="left knee a little stiff on the stairs this morning, fine now"))
    orch().request_exercise_plan(ExercisePlanRequestIn(plan_date=today))
    orch().request_diet_plan(DietPlanRequestIn(plan_date=today, notes="East Asian flavours please"))
    meal("2 boiled eggs and a bowl of rice")
    meal("170 g plain Greek yogurt with 80 g blueberries and a handful of almonds", answer="170 g yogurt, 80 g blueberries, 30 g almonds")
    orch().submit_diet_feedback(DietFeedbackIn(hunger=7, text="I was hungry by 11am, lunch feels too late"))
    plan = repo.current_released(user, "exercise")
    if plan and plan.activities:
        orch().submit_activity_feedback(plan.activities[0].id, ActivityFeedbackIn(completion="completed", exertion=5, pain=1, fatigue=4,
                                                                                  recovery_notes="comfortable pace, knee was fine"))
    return "seeded (yesterday + today for u_sam)"
