"""End-to-end scenarios through the HTTP API with the offline MockLLMClient (the demo script, as tests)."""
import os
import pathlib
import tempfile

import pytest

os.environ["BL_LLM_PROVIDER"] = "mock"
os.environ["BL_SEED_DEMO_FLOW"] = "false"   # scenarios below start from an empty day for Sam
_dbfile = pathlib.Path(tempfile.gettempdir()) / "balanceloop_test_e2e.db"
os.environ["BL_DATABASE_URL"] = f"sqlite:///{_dbfile}"

from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import get_llm  # noqa: E402
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
get_llm.cache_clear()
from app.main import app  # noqa: E402

SAM = {"X-User-Id": "u_sam"}
ALEX = {"X-User-Id": "u_alex"}
FOUNDER = {"X-User-Id": "founder"}
CHECKIN_OK = {"sleep_quality": 4, "fatigue": 3, "soreness": 2, "pain": 0, "recent_activity": "walked 20 min", "available_time_min": 40}


@pytest.fixture(scope="module")
def client():
    if _dbfile.exists():
        _dbfile.unlink()
    with TestClient(app) as c:
        c.post("/api/admin/reset-demo", params={"demo_flow": "false"})   # scenarios start from an empty day for Sam
        yield c


def post(c, url, body, h=SAM):
    r = c.post(url, json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- UC05 / UC06 fitness line
def test_uc05_missing_information_never_ready(client):
    d = post(client, "/api/readiness/checkins", {"sleep_quality": 4, "fatigue": 3})
    assert d["status"] == "clarification" and "pain" in d["message"]


def test_uc06_without_readiness_keeps_placeholder(client):
    d = post(client, "/api/exercise/plans", {})
    assert d["status"] == "pending_readiness"
    assert any(t["step"] == "createInternalPlaceholder" for t in d["trace"])


def test_uc05_ready_then_uc06_released(client):
    d = post(client, "/api/readiness/checkins", CHECKIN_OK)
    assert d["status"] == "info" and d["content"]["assessment"]["result"] == "Ready"
    d = post(client, "/api/exercise/plans", {})
    assert d["status"] == "released" and d["review"]["decision"] == "Approve" and d["review"]["risk_level"] == "Low"
    assert d["content"]["activities"] and all(a["intensity"] in ("light", "light-moderate") for a in d["content"]["activities"])
    steps = [t["step"] for t in d["trace"]]
    assert "applyHardRules" in steps and "computeRiskScore" in steps and "release" in steps
    assert any(t["llm_used"] for t in d["trace"])  # LLM drafted, rules decided


# ---------------------------------------------------------------- UC03 → UC09 integration with the released exercise plan
def test_uc03_diet_reconciled_into_daily_plan(client):
    d = post(client, "/api/diet/plans", {})
    assert d["status"] == "released" and d["content"]["kind"] == "integrated"
    assert d["content"]["diet"]["total_kcal"] >= 1200
    assert any(t["step"] == "findAcceptedCounterpart" for t in d["trace"]) and any(t["step"] == "detectConflicts" for t in d["trace"])


# ---------------------------------------------------------------- UC02 food
def test_uc02_food_analysis_released_with_uncertainty(client):
    d = post(client, "/api/food/entries", {"text": "2 boiled eggs and a bowl of rice"})
    assert d["status"] == "released"
    e = d["content"]["entry"]
    assert e["status"] == "Released" and e["confidence"] < 1 and e["uncertainty_range"]["kcal_low"] < e["nutrient_estimate"]["kcal"]


def test_uc02_clarification_then_allergen_notice(client):
    d = post(client, "/api/food/entries", {"text": "peanut butter toast"})
    assert d["status"] == "clarification"
    eid = d["content"]["entry"]["id"]
    d = post(client, f"/api/food/entries/{eid}/clarify", {"answer": "2 slices and 1 tbsp"})
    assert d["status"] == "released" and any("peanut" in f for f in d["content"]["entry"]["safety_flags"])


def test_uc02_unidentifiable_asks(client):
    d = post(client, "/api/food/entries", {"text": "something delicious"})
    assert d["status"] == "clarification"


# ---------------------------------------------------------------- UC10 hard rules via diet / feedback
def test_hr01_allergen_in_plan_blocked_with_safe_fallback(client):
    d = post(client, "/api/diet/plans", {"notes": "I love satay sauce"})
    assert d["status"] == "safe_response" and "HR-01" in d["review"]["triggered_rules"]
    assert "HR-01" in d["message"] and "General guidance" in d["message"]


def test_uc04_punitive_request_declined(client):
    d = post(client, "/api/diet/feedback", {"text": "I ate too much today so tomorrow I will skip dinner and only drink water"})
    assert "declined" in d["message"]
    assert any(t["step"] == "checkAgainstPunitiveRule" for t in d["trace"])


def test_uc04_hunger_minimal_change_released(client):
    d = post(client, "/api/diet/feedback", {"hunger": 8, "text": "I was really hungry by 11am"})
    assert d["status"] == "released" and "20%" in d["message"]


# ---------------------------------------------------------------- UC07 / UC08
def _first_activity_id(client):
    plan = client.get("/api/plans/exercise/current", headers=SAM).json()["plan"]
    return plan["activities"][0]["id"]


def test_uc07_feedback_and_uc08_adaptation(client):
    aid = _first_activity_id(client)
    d = post(client, f"/api/exercise/activities/{aid}/feedback", {"completion": "partial", "exertion": 5, "pain": 1, "fatigue": 4, "recovery_notes": "fine"})
    assert d["status"] == "info"
    d = post(client, "/api/exercise/plans/adapt", {})
    assert d["status"] == "released"
    assert any(t["step"] == "applyLoadRule" for t in d["trace"])


def test_uc05_history_comes_from_the_repository(client):
    h = client.get("/api/readiness/history", headers=SAM).json()
    assert h["recorded_activity"] and "Recorded in the app" in h["summary"]
    d = post(client, "/api/readiness/checkins", {**CHECKIN_OK, "recent_activity": None})   # the user adds nothing: fine
    assert d["status"] == "info" and any("Recorded in the app" in e for e in d["content"]["assessment"]["evidence"])
    d = post(client, "/api/readiness/checkins", {**CHECKIN_OK, "recent_activity": "cycled 10 min to work"})
    assert any("Reported by the user" in e for e in d["content"]["assessment"]["evidence"])


def test_uc07_chest_pain_is_critical_incident(client):
    aid = _first_activity_id(client)
    d = post(client, f"/api/exercise/activities/{aid}/feedback", {"completion": "partial", "exertion": 6, "pain": 2, "fatigue": 5, "recovery_notes": "I had chest pain and felt faint"})
    assert d["status"] == "support_notice" and "000" in d["message"]
    inc = client.get("/api/founder/incidents", headers=FOUNDER).json()
    assert any(i["severity"] == "critical" and "HR-02" in (i["rule_id"] or "") for i in inc)


def test_planning_paused_until_founder_acknowledges_incident(client):
    d = post(client, "/api/exercise/plans/adapt", {})
    assert d["status"] == "blocked" and d["extra"].get("paused")
    d = post(client, "/api/readiness/checkins", CHECKIN_OK)          # recording stays available
    assert d["status"] == "info"
    inc = [i for i in client.get("/api/founder/incidents", headers=FOUNDER).json() if i["severity"] == "critical" and not i["acknowledged"]]
    for i in inc:
        post(client, f"/api/founder/incidents/{i['id']}/ack", {}, FOUNDER)
    d = post(client, "/api/exercise/plans/adapt", {})
    assert d["status"] == "released"


def test_uc05_pain_gives_recovery_and_hr03_blocks_moderate_plan(client):
    d = post(client, "/api/readiness/checkins", {**CHECKIN_OK, "pain": 5, "pain_affects_activity": True, "free_text": "knee hurts"})
    assert d["content"]["assessment"]["result"] == "Recovery"
    d = post(client, "/api/exercise/plans", {"notes": "push me harder", "plan_date": "2030-01-01"})  # no counterpart that day → UC10 alone
    assert d["status"] == "safe_response" and "HR-03" in d["review"]["triggered_rules"]


def test_uc09_daily_plan_recovery_day_released_light(client):
    d = post(client, "/api/daily-plan", {})
    assert d["status"] == "released"
    assert all(a["intensity"] == "light" for a in d["content"]["exercise"]["activities"] if not a["paused"])


# ---------------------------------------------------------------- fail-closed (UC10 2b / 6a)
def test_policy_mismatch_fails_closed(client):
    post(client, "/api/founder/policies/0.9-draft/activate", {}, FOUNDER)
    d = post(client, "/api/diet/plans", {})
    assert d["status"] == "safe_response" and any(t["step"] == "failClosed" for t in d["trace"])
    post(client, "/api/founder/policies/1.0/activate", {}, FOUNDER)


def test_audit_failure_fails_closed(client):
    post(client, "/api/founder/policies/1.0/flags", {"simulate_audit_failure": True}, FOUNDER)
    d = post(client, "/api/diet/plans", {})
    assert d["status"] == "safe_response" and d["extra"].get("fail_closed")
    post(client, "/api/founder/policies/1.0/flags", {"simulate_audit_failure": False}, FOUNDER)


# ---------------------------------------------------------------- UC01 with a fresh user
def test_uc01_consent_profile_and_hr05(client):
    d = post(client, "/api/food/entries", {"text": "banana"}, ALEX)
    assert d["status"] == "blocked"
    post(client, "/api/consent", {"scope": "core", "granted": True}, ALEX)
    d = post(client, "/api/profile", {"goals": ["lose a little weight"], "allergy_status": "unknown", "available_time_min": 30}, ALEX)
    assert d["saved"] and d["status"] == "Incomplete"
    d = post(client, "/api/diet/plans", {}, ALEX)
    assert d["status"] == "clarification"
    d = post(client, "/api/food/entries", {"text": "1 medium banana"}, ALEX)
    assert d["status"] == "withheld" and "HR-05" in d["review"]["triggered_rules"]
    d = post(client, "/api/profile", {"goals": ["lose weight"], "allergy_status": "none", "allergies": ["milk"], "available_time_min": 30}, ALEX)
    assert d["saved"] is False and d["status"] == "Conflict"
    d = post(client, "/api/profile", {"goals": ["lose weight"], "allergy_status": "none", "available_time_min": 45}, ALEX)
    assert d["saved"] and d["version"] == 2
    d = post(client, "/api/diet/plans", {}, ALEX)
    assert d["status"] == "released"


def test_medium_risk_revised_then_released(client):
    post(client, "/api/readiness/checkins", {**CHECKIN_OK, "available_time_min": 45}, ALEX)
    d = post(client, "/api/exercise/plans", {"notes": "push me harder today", "plan_date": "2030-01-02"}, ALEX)
    assert d["status"] == "released" and d["review"]["repair_count"] == 1
    assert d["review"]["decisions"][0]["decision"] == "ReviseAndReview" and d["review"]["decisions"][-1]["decision"] == "Approve"


def test_consent_withdrawal_stops_processing(client):
    post(client, "/api/consent", {"scope": "core", "granted": False}, ALEX)
    d = post(client, "/api/diet/plans", {}, ALEX)
    assert d["status"] == "blocked"


# ---------------------------------------------------------------- Founder: audit & replay
def test_founder_replay_has_trace_audit_and_cases(client):
    reqs = client.get("/api/founder/requests", headers=FOUNDER).json()
    assert reqs
    rp = client.get(f"/api/founder/requests/{reqs[0]['request_id']}/replay", headers=FOUNDER).json()
    assert rp["trace"] and rp["audit"]
    assert client.get("/api/founder/audit", headers=SAM).status_code == 403
