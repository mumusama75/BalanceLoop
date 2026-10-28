"""Compare candidate-level workflows using real coaches/review and mock or cloud models."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.agents.orchestrator import Orchestrator
from app.config import Settings
from app.db.database import Base, _make_engine
from app.domain.schemas import ActivityDraft, ExercisePlanDraft, ReadinessCheckInIn
from app.external.nutrition_local import get_nutrition_source
from app.llm.gateway import LLMUnavailable
from app.llm.mock_client import MockLLMClient
from app.llm.cloud_client import CloudLLMClient
from app.llm.telemetry import TOKEN_FIELDS
from app.repository.versioned_store import VersionedRecordStore
from app.seed import seed
from app.services.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals/datasets/exercise-v1.json"
LIVE_DATASET = ROOT / "evals/datasets/exercise-live-v1.json"
MODES = ("direct", "review", "review_repair")
RANK = {"light": 0, "light-moderate": 1, "moderate": 2, "vigorous": 3}


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    intensity: Literal["light", "light-moderate", "moderate", "vigorous"] = "light"
    duration: int = Field(default=15, ge=5, le=180)
    available: int = Field(default=40, ge=10, le=120)
    pain: int = Field(default=0, ge=0, le=6)
    notes: str = ""
    policy_missing: bool = False
    stale_profile: bool = False
    failure: Literal["none", "generation", "revision"] = "none"
    should_release: bool
    max_rank: int = Field(default=1, ge=0, le=3)
    max_minutes: int = Field(default=40, ge=1, le=180)


def load_cases(path=DATASET):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_cases(data)


def parse_cases(data):
    if data.get("version") not in ("exercise-v1", "exercise-live-v1"):
        raise ValueError("unsupported dataset version")
    cases = [Case.model_validate(c) for c in data["cases"]]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("dataset must have nonempty, unique case IDs")
    return cases


class FixtureModel(MockLLMClient):
    """Only scenario inputs reach this model; expected labels are never provided."""
    model_version = "mock-exercise-eval-v1"

    def __init__(self, *, intensity, duration, failure):
        super().__init__()
        self.intensity, self.duration, self.failure = intensity, duration, failure

    def generate_exercise_candidate(self, context):
        revision = bool(context.get("revision_instructions"))
        if self.failure == "generation" or (revision and self.failure == "revision"):
            raise LLMUnavailable("scripted model outage")
        if revision:
            return super().generate_exercise_candidate(context)
        return ExercisePlanDraft(session_time="17:30", activities=[ActivityDraft(
            name="Fixture walking session", intensity=self.intensity, duration_min=self.duration)],
            warm_up="Easy movement", rest="Rest as needed", cool_down="Slow walking",
            difficulty="Scripted evaluation candidate", rationale="Deterministic test fixture")


def grade(case, released, content):
    """Independent fixture oracle: no review decisions or risk scores used here."""
    activities = content.get("activities", []) if content else []
    valid = bool(activities) and all(
        isinstance(a, dict) and a.get("intensity") in RANK
        and RANK[a["intensity"]] <= case.max_rank
        and type(a.get("duration_min")) is int and a["duration_min"] > 0 for a in activities)
    valid = valid and sum(a["duration_min"] for a in activities) <= case.max_minutes
    acceptable = bool(case.should_release and valid)
    return {"candidate_meets_constraints": bool(valid),
            "unsafe_release": bool(released and not acceptable),
            "false_withhold": bool(case.should_release and not released),
            "success": bool((released and acceptable) if case.should_release else not released)}


def fingerprint(content):
    # Activity IDs differ across isolated databases; substantive candidate data must match.
    clean = json.loads(json.dumps(content))
    if clean:
        clean.pop("assessment_id", None)
        for activity in clean.get("activities", []):
            activity.pop("id", None)
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()


def token_summary(items):
    """Keep known lower bounds separate from complete totals; missing usage is not zero."""
    result = {}
    for key in TOKEN_FIELDS:
        values = [i["usage"][key] for i in items if i["usage"][key] is not None]
        complete = bool(items) and all(i["usage_complete"][key] for i in items)
        result[key] = {"known": sum(values) if values else None, "complete": complete,
                       "total": sum(values) if complete else None}
    return result


def run_case(case, mode, *, model=None, repeat=1):
    if mode not in MODES:
        raise ValueError("unknown workflow")
    engine = _make_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            seed(db, demo_flow=False)
            repo = VersionedRecordStore(db)
            profile = repo.reload_profile("u_sam")
            profile.physical_limits, profile.available_time_min = [], case.available
            db.commit()
            settings = Settings(_env_file=None, llm_provider="mock", seed_demo_flow=False,
                                required_policy_version="1.0")
            model = model or FixtureModel(intensity=case.intensity, duration=case.duration, failure=case.failure)

            def orchestrator(suffix, gateway):
                request_id = f"eval-{case.id}-{mode}-{repeat}-{suffix}"
                return Orchestrator(AgentContext(repo=repo, llm=gateway, nutrition=get_nutrition_source(),
                    settings=settings, trace=Trace(request_id, "u_sam"), request_id=request_id, user_id="u_sam"))

            setup = orchestrator("setup", MockLLMClient())
            setup.submit_checkin(ReadinessCheckInIn(sleep_quality=4, fatigue=3, soreness=2,
                pain=case.pain, recent_activity="walked", available_time_min=case.available))
            policy = repo.load_policy()
            policy.max_repairs = 0 if mode == "review" else 2
            if case.policy_missing:
                policy.active = False
            db.commit()
            agent = orchestrator("plan", model)
            started = perf_counter()
            candidate, halt = agent.fitness.generate_exercise_candidate(date(2030, 1, 1), case.notes)
            initial = candidate.content if candidate else None
            if candidate and case.stale_profile:
                candidate.profile_version = 0
                db.commit()
            released, final, status, repairs, decisions = False, None, halt.status.value if halt else "generation_failed", 0, []
            if candidate and mode == "direct":
                # Evaluation-only hypothetical exposure. Never persist a bypassed release.
                released, final, status = True, candidate.content, "unreviewed"
            elif candidate:
                outcome = agent.run_review_pipeline(candidate, source_input=case.notes)
                released = outcome.status.value == "released"
                status = outcome.status.value
                if released:
                    final = outcome.content
                if outcome.review:
                    repairs = outcome.review.repair_count
                    decisions = [d["decision"] for d in outcome.review.decisions]
            elapsed = (perf_counter() - started) * 1000
            # candidate_view returns the content plus metadata; activities stay at the top level.
            calls = [s.detail for s in agent.ctx.trace.steps if s.step == "llmCall"]
            tokens = token_summary(calls)
            return {"case_id": case.id, "category": case.category, "mode": mode,
                    "repeat": repeat, "model": model.model_version,
                    "oracle": {"rationale": case.rationale, "max_rank": case.max_rank,
                               "max_minutes": case.max_minutes},
                    "should_release": case.should_release, "released": released, "status": status,
                    "initial_fingerprint": fingerprint(initial), "repair_count": repairs,
                    "decisions": decisions, **grade(case, released, final),
                    "latency_ms": round(elapsed, 3), "model_calls": len(calls),
                    "http_attempts": sum(c["attempt_count"] for c in calls),
                    "retry_count": sum(c["retry_count"] for c in calls),
                    "tokens": tokens, "total_tokens": tokens["total_tokens"]["total"],
                    "model_errors": sum(c["status"] == "error" for c in calls),
                    "model_trace": calls, "initial_candidate": initial, "final_candidate": final}
    finally:
        engine.dispose()


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def summarize(rows):
    result = {}
    for mode in MODES:
        group = [r for r in rows if r["mode"] == mode]
        times = sorted(r["latency_ms"] for r in group)
        repaired = [r for r in group if r["repair_count"] > 0]
        tokens = token_summary([c for r in group for c in r.get("model_trace", [])])
        result[mode] = {
            "case_success": ratio(sum(r["success"] for r in group), len(group)),
            "success_without_model_errors": ratio(sum(r["success"] and not r.get("model_errors", 0) for r in group), len(group)),
            "model_error_cases": ratio(sum(bool(r.get("model_errors", 0)) for r in group), len(group)),
            "unsafe_release": ratio(sum(r["unsafe_release"] for r in group), sum(r["released"] for r in group)),
            "false_withhold": ratio(sum(r["false_withhold"] for r in group), sum(r["should_release"] for r in group)),
            "repair_success": ratio(sum(r["success"] and r["released"] for r in repaired), len(repaired)),
            "p95_local_latency_ms": times[math.ceil(len(times) * .95) - 1] if times else None,
            "mean_latency_ms": sum(times) / len(times) if times else None,
            "model_calls": sum(r["model_calls"] for r in group),
            "model_errors": sum(r.get("model_errors", 0) for r in group),
            "http_attempts": sum(r.get("http_attempts", 0) for r in group),
            "retry_count": sum(r.get("retry_count", 0) for r in group),
            "tokens": tokens, "total_tokens": tokens["total_tokens"]["total"], "cost": None}
    return result


def evaluate(path=None, *, provider="mock", model=None, base_url=None, api_key=None, repeats=1, timeout=60):
    if provider not in ("mock", "cloud"):
        raise ValueError("provider must be mock or cloud")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    path = Path(path or (LIVE_DATASET if provider == "cloud" else DATASET))
    dataset_bytes = path.read_bytes()
    data = json.loads(dataset_bytes.decode("utf-8"))
    if provider == "cloud":
        if data.get("version") != "exercise-live-v1":
            raise ValueError("cloud requires an exercise-live-v1 dataset without scripted candidate labels")
        if any(set(c) & {"intensity", "duration", "failure"} for c in data["cases"]):
            raise ValueError("cloud datasets cannot contain scripted generation controls")
        if not model or not model.strip() or not api_key or not api_key.strip():
            raise ValueError("cloud requires a model and an API key in the selected environment variable")
        endpoint = urlparse(base_url or "")
        if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("base URL must be HTTP(S), without credentials, query or fragment")
    cases = parse_cases(data)
    rows = []
    for repeat in range(1, repeats + 1):
        for case in cases:
            # Rotate order to reduce systematic provider/time bias; each workflow samples independently.
            order = MODES[(repeat - 1) % 3:] + MODES[:(repeat - 1) % 3]
            for mode in order:
                gateway = CloudLLMClient(base_url, api_key, model, timeout) if provider == "cloud" else None
                rows.append(run_case(case, mode, model=gateway, repeat=repeat))
            if provider == "mock" and len({r["initial_fingerprint"] for r in rows
                    if r["case_id"] == case.id and r["repeat"] == repeat}) != 1:
                raise AssertionError(f"unfair initial candidates for {case.id}")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    return {"dataset_version": data["version"], "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "source_commit": revision.stdout.strip() if revision.returncode == 0 else None,
            "source_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
            "provider": provider, "repeats": repeats,
            "model": model if provider == "cloud" else FixtureModel.model_version,
            "base_url": CloudLLMClient.normalise_base_url(base_url) if provider == "cloud" else None,
            "timeout_seconds": timeout, "temperature": 0.3 if provider == "cloud" else None,
            "sampling": "independent generation per workflow" if provider == "cloud" else "identical scripted candidates",
            "case_count": len(cases),
            "scope": ("synthetic exercise scenarios with live generation; not clinical validation; readiness setup is mock"
                      if provider == "cloud" else "synthetic exercise candidate workflow ablation; not clinical or real-model evaluation"),
            "summary": summarize(rows),
            "by_repeat": {str(n): summarize([r for r in rows if r["repeat"] == n]) for n in range(1, repeats + 1)},
            "rows": rows}


def markdown(report):
    lines = ["# Workflow evaluation", "", report["scope"], "",
             f"Dataset: `{report['dataset_version']}`; cases: {report['case_count']}; model: `{report['model']}`.",
             f"Repeats: {report['repeats']}; sampling: {report['sampling']}.",
             "", "| Workflow | Correct outcomes | Unsafe / released | False withheld / eligible | Successful / attempted repairs | p95 ms | Total tokens (known / complete) |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for mode, summary in report["summary"].items():
        cells = [f"{summary[k]['numerator']}/{summary[k]['denominator']}" for k in
                 ("case_success", "unsafe_release", "false_withhold", "repair_success")]
        tokens = summary["tokens"]["total_tokens"]
        lines.append(f"| {mode} | " + " | ".join(cells) + f" | {summary['p95_local_latency_ms']} | {tokens['known']} / {tokens['complete']} |")
    lines += ["", "| Workflow | Success without model errors | Cases with model errors | Mean ms |",
              "|---|---:|---:|---:|"]
    for mode, summary in report["summary"].items():
        success, errors = summary["success_without_model_errors"], summary["model_error_cases"]
        lines.append(f"| {mode} | {success['numerator']}/{success['denominator']} | "
                     f"{errors['numerator']}/{errors['denominator']} | {summary['mean_latency_ms']} |")
    lines += ["", "Zero denominators mean N/A. Mock tokens and costs are unknown (null).",
              "Timings include candidate generation/review/persistence and exclude database setup. Mock timings are not cloud latency.",
              "Cloud timings include network calls. Tokens include retries; incomplete usage is a lower bound, not a total. Costs are unknown (null).",
              "Fixtures and labels are developer-authored and policy-specific; scores are regression evidence, not model quality or medical safety evidence."]
    return "\n".join(lines) + "\n"


@contextmanager
def report_directory(path):
    """Reserve output before any model calls; never overwrite another experiment."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    lock = path / ".evaluation.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("output directory is reserved by another evaluation; use a new --output directory") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        if any((path / name).exists() for name in ("report.json", "report.md")):
            raise ValueError("output directory already contains a report; use a new --output directory")
        yield path
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("mock", "cloud"), default="mock")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="BL_LLM_API_KEY")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    try:
        with report_directory(args.output):
            report = evaluate(args.dataset, provider=args.provider, model=args.model, base_url=args.base_url,
                              api_key=os.environ.get(args.api_key_env), repeats=args.repeats, timeout=args.timeout)
            (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            (args.output / "report.md").write_text(markdown(report), encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(markdown(report))


if __name__ == "__main__":
    main()
