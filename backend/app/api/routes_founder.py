"""Founder console: policy, audit log, incidents (AR-09, AR-10)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..db import models as m
from ..domain.schemas import PolicyIn
from ..repository.base import AuditStoreError
from ..repository.versioned_store import VersionedRecordStore
from ..util import new_id
from .deps import founder_user, get_repo
from .routes_review import case_view

router = APIRouter(prefix="/api/founder", tags=["founder console"])


def policy_view(p: m.ReviewPolicy) -> dict:
    return {"id": p.id, "version": p.version, "hard_rules": p.hard_rules, "risk_thresholds": p.risk_thresholds, "max_repairs": p.max_repairs,
            "active": p.active, "notes": p.notes, "created_at": p.created_at.isoformat()}


@router.get("/policies")
def list_policies(_=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [policy_view(p) for p in repo.list_policies()]


@router.post("/policies")
def save_policy(data: PolicyIn, founder=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    p = repo.save_policy(m.ReviewPolicy(id=new_id("pol"), version=data.version, hard_rules=data.hard_rules, risk_thresholds=data.risk_thresholds,
                                        max_repairs=data.max_repairs, notes=data.notes, active=False))
    if data.activate:
        repo.activate_policy(data.version)
    repo.append_audit(new_id("req"), founder.id, "Founder", "configurePolicy", decision="saved", versions={"policy_version": data.version},
                      payload={"activated": data.activate})
    return policy_view(repo.load_policy(data.version))


@router.post("/policies/{version}/activate")
def activate(version: str, founder=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    p = repo.activate_policy(version)
    if p is None:
        raise HTTPException(404, "policy version not found")
    repo.append_audit(new_id("req"), founder.id, "Founder", "activatePolicy", decision="activated", versions={"policy_version": version})
    return policy_view(p)


@router.post("/policies/deactivate-all")
def deactivate_all(founder=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    """Demo: no active policy → every review fails closed."""
    repo.deactivate_all_policies()
    repo.append_audit(new_id("req"), founder.id, "Founder", "deactivateAllPolicies", decision="none active")
    return {"active": None}


@router.post("/policies/{version}/flags")
def set_flags(version: str, flags: dict, founder=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    """Demo toggles stored in risk_thresholds, e.g. {"simulate_audit_failure": true} (UC10 6a)."""
    p = repo.load_policy(version)
    if p is None:
        raise HTTPException(404, "policy version not found")
    # audit first: once simulate_audit_failure is on, the audit store itself refuses writes
    try:
        repo.append_audit(new_id("req"), founder.id, "Founder", "setPolicyFlags", versions={"policy_version": version}, payload=flags)
    except AuditStoreError:
        pass
    p.risk_thresholds = {**(p.risk_thresholds or {}), **flags}
    repo.commit()
    return policy_view(p)


@router.get("/audit")
def audit(request_id: Optional[str] = None, user_id: Optional[str] = None, _=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [{"id": a.id, "request_id": a.request_id, "user_id": a.user_id, "timestamp": a.timestamp.isoformat(), "actor": a.actor,
             "action": a.action, "decision": a.decision, "versions": a.versions, "payload": a.payload} for a in repo.list_audit(request_id, user_id)]


@router.get("/requests")
def requests(user_id: Optional[str] = None, _=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return repo.list_request_ids(user_id)


@router.get("/requests/{request_id}/replay")
def replay(request_id: str, _=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    """AuditLog.replay(requestId): the full chain — trace, audit records, review cases, conflicts — on one timeline."""
    return {"request_id": request_id,
            "trace": [{"seq": s.seq, "agent": s.agent, "step": s.step, "llm_used": s.llm_used, "model_version": s.model_version,
                       "summary": s.summary, "detail": s.detail, "at": s.created_at.isoformat()} for s in repo.load_trace(request_id)],
            "audit": [{"id": a.id, "timestamp": a.timestamp.isoformat(), "actor": a.actor, "action": a.action, "decision": a.decision,
                       "versions": a.versions, "payload": a.payload} for a in reversed(repo.list_audit(request_id))],
            "cases": [case_view(c, repo) for c in repo.cases_for_request(request_id)],
            "conflicts": [{"round": c.round, "type": c.type, "description": c.description, "responsible_agent": c.responsible_agent, "resolved": c.resolved}
                          for c in repo.conflicts_for_request(request_id)]}


@router.get("/incidents")
def incidents(_=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [{"id": i.id, "user_id": i.user_id, "request_id": i.request_id, "candidate_id": i.candidate_id, "rule_id": i.rule_id, "severity": i.severity,
             "description": i.description, "acknowledged": i.acknowledged, "created_at": i.created_at.isoformat()} for i in repo.list_incidents()]


@router.post("/incidents/{incident_id}/ack")
def ack(incident_id: str, founder=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    inc = repo.ack_incident(incident_id)
    if inc is None:
        raise HTTPException(404, "incident not found")
    repo.append_audit(inc.request_id, founder.id, "Founder", "reviewIncident", decision="acknowledged", payload={"incident_id": incident_id})
    return {"id": inc.id, "acknowledged": inc.acknowledged}


@router.get("/notifications")
def founder_notifications(_=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [{"id": n.id, "kind": n.kind, "message": n.message, "request_id": n.request_id, "created_at": n.created_at.isoformat()}
            for n in repo.list_notifications("founder")]


@router.get("/cases")
def all_cases(_=Depends(founder_user), repo: VersionedRecordStore = Depends(get_repo)):
    return [case_view(c, repo) for c in repo.list_cases()]
