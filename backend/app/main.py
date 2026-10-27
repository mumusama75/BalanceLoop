"""BalanceLoop backend — FastAPI application entry point."""
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_fitness, routes_founder, routes_nutrition, routes_review, routes_user
from .api.deps import get_llm
from .config import get_settings
from .db.database import Base, SessionLocal, engine
from .db import models  # noqa: F401  (register tables)
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield


settings = get_settings()
app = FastAPI(title="BalanceLoop API", version="0.2.0", lifespan=lifespan,
              description="One-Person AI Company for reviewed lifestyle support — Orchestrator, Nutrition Coach, Fitness Coach and Safety Supervisor.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for r in (routes_user.router, routes_nutrition.router, routes_fitness.router, routes_review.router, routes_founder.router):
    app.include_router(r)


@app.get("/api/health", tags=["system"])
def health():
    llm = get_llm()
    with SessionLocal() as db:
        from .repository.versioned_store import VersionedRecordStore
        p = VersionedRecordStore(db).load_policy()
    return {"status": "ok", "llm_provider": settings.llm_provider, "llm_model_version": llm.model_version,
            "required_policy_version": settings.required_policy_version, "active_policy_version": p.version if p else None}


@app.post("/api/admin/reset-demo", tags=["system"])
def reset_demo(demo_flow: Optional[bool] = None):
    """Drop and recreate all tables, then re-seed (demo convenience). ``demo_flow`` overrides BL_SEED_DEMO_FLOW."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        return {"reset": True, **seed(db, demo_flow=demo_flow)}
