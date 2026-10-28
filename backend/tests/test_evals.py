"""Offline workflow ablation contracts; scores describe fixtures, not model quality."""
import hashlib
import json

import httpx
import pytest

from evals.run import Case, MODES, evaluate, fingerprint, grade, load_cases, markdown, ratio, summarize
from evals import run


@pytest.fixture(scope="module")
def report():
    with pytest.MonkeyPatch.context() as patch:
        def no_network(*args, **kwargs):
            pytest.fail("mock evaluation attempted HTTP")
        patch.setattr(httpx.Client, "send", no_network)
        return evaluate()


def row(report, case_id, mode):
    return next(r for r in report["rows"] if (r["case_id"], r["mode"]) == (case_id, mode))


def test_matrix_is_complete_fair_and_offline(report):
    assert len(report["rows"]) == report["case_count"] * len(MODES)
    assert len(report["dataset_sha256"]) == 64
    for case in load_cases():
        rows = [row(report, case.id, mode) for mode in MODES]
        assert len({r["initial_fingerprint"] for r in rows}) == 1
        for r in rows:
            assert r["model_calls"] == len(r["model_trace"]) > 0
            assert r["http_attempts"] == r["retry_count"] == 0
            assert r["total_tokens"] is None
            assert r["latency_ms"] >= 0
            assert 0 <= r["repair_count"] <= 2


@pytest.mark.parametrize("mode", MODES)
def test_safe_candidate_and_generation_failure(report, mode):
    assert row(report, "safe-light", mode)["released"]
    failure = row(report, "generation-outage", mode)
    assert failure["success"] and not failure["released"]
    assert failure["initial_candidate"] is None
    assert failure["model_calls"] == 1


def test_review_blocks_and_repair_recovers(report):
    direct = row(report, "moderate-repair", "direct")
    review = row(report, "moderate-repair", "review")
    repaired = row(report, "moderate-repair", "review_repair")
    assert direct["unsafe_release"] and not direct["success"]
    assert review["false_withhold"] and review["repair_count"] == 0
    assert repaired["released"] and repaired["success"] and repaired["repair_count"] == 1
    assert repaired["model_calls"] > review["model_calls"] > direct["model_calls"]


@pytest.mark.parametrize("case_id", ["critical-symptom", "eating-warning", "missing-policy", "stale-profile", "recovery-nonlight", "vigorous-fallback"])
def test_blocking_cases_are_not_repaired_into_release(report, case_id):
    assert row(report, case_id, "direct")["unsafe_release"]
    for mode in ("review", "review_repair"):
        result = row(report, case_id, mode)
        assert result["success"] and not result["released"]
        assert result["repair_count"] == 0


def test_revision_failure_stays_visible_as_task_failure(report):
    result = row(report, "revision-outage", "review_repair")
    assert result["repair_count"] == 1
    assert result["false_withhold"] and not result["success"]
    assert not result["unsafe_release"]


def test_summary_denominators_are_independent_of_workflow_success():
    rows = [dict(mode="direct", success=False, unsafe_release=True, released=True,
                 false_withhold=False, should_release=False, repair_count=0, latency_ms=10, model_calls=1),
            dict(mode="direct", success=False, unsafe_release=False, released=False,
                 false_withhold=True, should_release=True, repair_count=1, latency_ms=20, model_calls=3)]
    summary = summarize(rows)
    assert summary["direct"]["case_success"] == ratio(0, 2)
    assert summary["direct"]["unsafe_release"] == ratio(1, 1)
    assert summary["direct"]["false_withhold"] == ratio(1, 1)
    assert summary["direct"]["repair_success"] == ratio(0, 1)
    assert summary["direct"]["p95_local_latency_ms"] == 20
    assert summary["review"]["case_success"]["rate"] is None
    assert summary["review"]["p95_local_latency_ms"] is None


@pytest.mark.parametrize("activities", [[], [{"intensity":"invalid","duration_min":10}],
    [{"intensity":"light","duration_min":-1}], [{"intensity":"light","duration_min":41}],
    [{"intensity":"moderate","duration_min":10}], [{"intensity":"light","duration_min":True}]])
def test_oracle_rejects_constraint_violations_without_consulting_reviewer(activities):
    case = Case(id="oracle", category="unit", rationale="Independent constraint test", should_release=True)
    result = grade(case, True, {"activities":activities})
    assert result["unsafe_release"] and not result["success"]


@pytest.mark.parametrize("mutation", ["version", "duplicate", "empty", "unknown", "missing-label", "empty-id"])
def test_invalid_datasets_fail_explicitly(tmp_path, mutation):
    case = load_cases()[0].model_dump()
    data = {"version":"exercise-v1", "cases":[case]}
    if mutation == "version": data["version"] = "unknown"
    elif mutation == "duplicate": data["cases"].append(case)
    elif mutation == "empty": data["cases"] = []
    elif mutation == "unknown": case["unexpected"] = True
    elif mutation == "missing-label": del case["should_release"]
    elif mutation == "empty-id": case["id"] = ""
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError): load_cases(path)


def test_fingerprint_ignores_only_generated_identifiers():
    first = {"assessment_id":"a", "activities":[{"id":"a", "duration_min":10}]}
    second = {"assessment_id":"b", "activities":[{"id":"b", "duration_min":10}]}
    assert fingerprint(first) == fingerprint(second)
    second["activities"][0]["duration_min"] = 11
    assert fingerprint(first) != fingerprint(second)


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_report_uses_dataset_snapshot_when_file_changes(tmp_path, monkeypatch, change):
    case = load_cases()[0].model_dump()
    original = json.dumps({"version": "exercise-v1", "cases": [case]}).encode("utf-8")
    path = tmp_path / "cases.json"
    path.write_bytes(original)
    original_run_case = run.run_case
    calls = 0

    def change_dataset(*args, **kwargs):
        nonlocal calls
        if calls == 0:
            if change == "replace":
                path.write_text('{"version":"changed","cases":[]}', encoding="utf-8")
            else:
                path.unlink()
        calls += 1
        return original_run_case(*args, **kwargs)

    monkeypatch.setattr(run, "run_case", change_dataset)
    result = evaluate(path, repeats=2)
    assert result["dataset_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["dataset_version"] == "exercise-v1"
    assert result["case_count"] == 1
    assert len(result["rows"]) == calls == 6
    assert {r["case_id"] for r in result["rows"]} == {case["id"]}


def test_report_discloses_mock_scope(report):
    json.dumps(report)
    text = markdown(report)
    assert "not clinical or real-model evaluation" in text
    assert "unknown (null)" in text
    assert "not cloud latency" in text
