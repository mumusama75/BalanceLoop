"""UC01 profile & consent, users, notifications."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..agents.common import candidate_view
from ..agents.orchestrator import Orchestrator
from ..domain.schemas import ConsentIn, ProfileIn, ProfileOut, UserOut
from ..repository.versioned_store import VersionedRecordStore
from .deps import current_user, get_orchestrator, get_repo

router = APIRouter(prefix="/api", tags=["users & profile (UC01)"])


@router.get("/users", response_model=List[UserOut])
def list_users(repo: VersionedRecordStore = Depends(get_repo)):
    return repo.list_users()


@router.get("/users/me", response_model=UserOut)
def me(user=Depends(current_user)):
    return user


def _profile_out(p, repo) -> ProfileOut:
    out = ProfileOut.model_validate(p)
    out.consents = repo.consents(p.user_id)
    return out


@router.get("/profile")
def get_profile(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    p = repo.reload_profile(user.id)
    if p is None:
        return {"profile": None, "consents": repo.consents(user.id)}
    return {"profile": _profile_out(p, repo), "consents": repo.consents(user.id)}


@router.get("/profile/versions", response_model=List[ProfileOut])
def profile_versions(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [_profile_out(p, repo) for p in repo.profile_versions(user.id)]


@router.post("/profile")
def save_profile(data: ProfileIn, orch: Orchestrator = Depends(get_orchestrator)):
    res = orch.submit_profile(data)
    p = orch.repo.reload_profile(orch.ctx.user_id)
    res["profile"] = _profile_out(p, orch.repo).model_dump() if p else None
    res["consents"] = orch.repo.consents(orch.ctx.user_id)
    return res


@router.post("/consent")
def consent(data: ConsentIn, orch: Orchestrator = Depends(get_orchestrator)):
    return orch.record_consent(data.scope, data.granted)


@router.get("/notifications")
def notifications(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [{"id": n.id, "kind": n.kind, "message": n.message, "request_id": n.request_id, "read": n.read,
             "created_at": n.created_at.isoformat()} for n in repo.list_notifications("user", user.id)]


@router.post("/notifications/read")
def mark_notifications_read(user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    n = 0
    for ntf in repo.list_notifications("user", user.id, limit=500):
        if not ntf.read:
            ntf.read = True; n += 1
    repo.commit()
    return {"marked": n}


@router.get("/plans/{kind}/current")
def current_plan(kind: str, user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    if kind not in ("diet", "exercise", "integrated"):
        raise HTTPException(404, "unknown plan kind")
    c = repo.current_released(user.id, kind)
    return {"plan": candidate_view(c) if c else None}


@router.get("/plans/{kind}/versions")
def plan_versions(kind: str, user=Depends(current_user), repo: VersionedRecordStore = Depends(get_repo)):
    if kind not in ("diet", "exercise", "integrated", "food_analysis"):
        raise HTTPException(404, "unknown plan kind")
    return [candidate_view(c) for c in repo.candidate_versions(user.id, kind)]
