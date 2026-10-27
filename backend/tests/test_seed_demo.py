"""The demo seed runs a whole day for Sam through the real agents on an empty database."""
import os

os.environ.setdefault("BL_LLM_PROVIDER", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAM = {"X-User-Id": "u_sam"}


def test_seeded_day_is_visible_everywhere():
    with TestClient(app) as c:
        r = c.post("/api/admin/reset-demo", params={"demo_flow": "true"}).json()
        assert r["demo_flow"].startswith("seeded")
        assert c.get("/api/readiness/latest", headers=SAM).json()["assessment"]["result"] == "Ready"
        assert c.get("/api/plans/exercise/current", headers=SAM).json()["plan"]["released"]
        assert c.get("/api/plans/integrated/current", headers=SAM).json()["plan"]["released"]
        entries = c.get("/api/food/entries", headers=SAM).json()
        assert len(entries) >= 2 and all(e["status"] == "Released" for e in entries)
        h = c.get("/api/readiness/history", headers=SAM).json()
        assert h["recorded_activity"] and h["previous"]
        assert len(c.get("/api/exercise/feedback", headers=SAM).json()) >= 1
        versions = c.get("/api/plans/exercise/versions", headers=SAM).json()
        assert len({v["plan_date"] for v in versions}) >= 2          # yesterday + today
        assert c.get("/api/review/cases", headers=SAM).json()
        c.post("/api/admin/reset-demo", params={"demo_flow": "false"})  # leave the shared test database empty again
