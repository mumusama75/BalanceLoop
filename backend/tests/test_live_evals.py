"""Exercise the real cloud gateway and eval pipeline with offline HTTP responses."""
import json
import sys

import httpx
import pytest

from evals.run import DATASET, FixtureModel, evaluate, main


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version":"exercise-live-v1", "cases":[{
        "id":"normal", "category":"normal", "rationale":"Low intensity required", "should_release":True}]}))
    return path


@pytest.fixture
def cloud(monkeypatch):
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs)
        payload = json.loads(kwargs["json"]["messages"][1]["content"])
        assert "should_release" not in payload and "max_rank" not in payload
        if "triggered_rules" in payload:
            content = {"instructions":["Lower intensity to light"], "rule_ids":[], "summary":"Reduce load"}
        else:
            intensity = "light" if payload.get("revision_instructions") else "moderate"
            content = FixtureModel(intensity=intensity, duration=15, failure="none").generate_exercise_candidate({}).model_dump(mode="json")
        return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(content)}}],
            "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    return requests


def run(path, **kwargs):
    return evaluate(path, provider="cloud", model="test-model", base_url="https://model.example/v1",
                    api_key="secret-test-key", **kwargs)


def test_cloud_repeats_repair_tokens_and_model_selection(dataset, cloud):
    report = run(dataset, repeats=2)
    assert len(report["rows"]) == 6
    assert len(cloud) == 12  # generation (3), revision drafting (2), repair (1) per repeat
    assert all(r["json"]["model"] == "test-model" for r in cloud)
    assert all(r["timeout"] == 60 for r in cloud)
    assert [r["mode"] for r in report["rows"]][3:] == ["review","review_repair","direct"]
    summary = report["summary"]
    assert summary["direct"]["case_success"]["rate"] == 0
    assert summary["review"]["false_withhold"]["rate"] == 1
    assert summary["review_repair"]["case_success"]["rate"] == 1
    assert [summary[m]["total_tokens"] for m in ("direct","review","review_repair")] == [30,60,90]
    assert report["by_repeat"]["1"]["review_repair"]["total_tokens"] == 45
    assert "secret-test-key" not in json.dumps(report)
    second = evaluate(dataset, provider="cloud", model="another-model", base_url="https://model.example",
                      api_key="secret-test-key", timeout=12)
    assert second["model"] == "another-model"
    assert cloud[-1]["json"]["model"] == "another-model" and cloud[-1]["timeout"] == 12


def test_http_failure_is_recorded_and_all_modes_continue(dataset, monkeypatch):
    def post(url, **kwargs):
        return httpx.Response(503, json={"error":"secret-provider-text"}, request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx, "post", post)
    report = run(dataset, repeats=2)
    assert len(report["rows"]) == 6
    for row in report["rows"]:
        assert not row["success"] and row["model_errors"] == 1
        assert row["total_tokens"] is None and not row["tokens"]["total_tokens"]["complete"]
    assert "secret-provider-text" not in json.dumps(report)


def test_schema_retry_usage_and_missing_usage_are_not_lost(dataset, monkeypatch):
    count = 0
    draft = FixtureModel(intensity="light", duration=10, failure="none").generate_exercise_candidate({}).model_dump(mode="json")
    def post(url, **kwargs):
        nonlocal count
        count += 1
        body = {"choices":[{"message":{"content":"not json" if count % 2 else json.dumps(draft)}}]}
        if count % 2:
            body["usage"] = {"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}
        return httpx.Response(200, json=body, request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx,"post",post)
    report = run(dataset)
    for row in report["rows"]:
        assert row["success"] and row["retry_count"] == 1 and row["http_attempts"] == 2
        assert row["total_tokens"] is None
        assert row["tokens"]["total_tokens"] == {"known":15,"complete":False,"total":None}
    assert report["summary"]["direct"]["tokens"]["total_tokens"]["known"] == 15


def test_cloud_allows_independent_candidates(dataset, monkeypatch):
    counter = 0
    def post(url, **kwargs):
        nonlocal counter
        counter += 1
        draft = FixtureModel(intensity="light", duration=counter + 5, failure="none").generate_exercise_candidate({})
        return httpx.Response(200, json={"choices":[{"message":{"content":draft.model_dump_json()}}]},
                              request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx,"post",post)
    report = run(dataset)
    assert len({r["initial_fingerprint"] for r in report["rows"]}) == 3
    assert all(r["success"] for r in report["rows"])


def test_blocked_case_outage_is_not_error_free_success(dataset, monkeypatch):
    content = json.loads(dataset.read_text())
    content["cases"][0]["should_release"] = False
    dataset.write_text(json.dumps(content))
    def post(url, **kwargs):
        raise httpx.ReadTimeout("private provider diagnostics")
    monkeypatch.setattr(httpx,"post",post)
    report = run(dataset)
    for summary in report["summary"].values():
        assert summary["case_success"]["rate"] == 1
        assert summary["success_without_model_errors"]["rate"] == 0
        assert summary["model_error_cases"]["rate"] == 1
    assert "private provider diagnostics" not in json.dumps(report)


@pytest.mark.parametrize("repeats", [0,-1,True,1.5])
def test_invalid_repeat_counts_are_rejected(repeats):
    with pytest.raises(ValueError, match="repeats"): evaluate(repeats=repeats)


@pytest.mark.parametrize("timeout", [0,-1,float("inf"),float("nan")])
def test_invalid_timeouts_are_rejected(timeout):
    with pytest.raises(ValueError, match="timeout"): evaluate(timeout=timeout)


def test_cloud_rejects_mock_labels_and_missing_credentials(dataset):
    with pytest.raises(ValueError, match="dataset"): run(DATASET)
    with pytest.raises(ValueError, match="API key"):
        evaluate(dataset, provider="cloud", model="model", base_url="https://model.example")
    content = json.loads(dataset.read_text())
    content["cases"][0]["intensity"] = "moderate"
    dataset.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="scripted"): run(dataset)


@pytest.mark.parametrize("url", ["https://key@model.example", "https://model.example?key=secret", "file:///tmp/model"])
def test_endpoint_credentials_are_rejected(dataset, url):
    with pytest.raises(ValueError, match="base URL"):
        evaluate(dataset, provider="cloud", model="m", base_url=url, api_key="key")


def test_cloud_cli_uses_live_default_and_env_key(monkeypatch, tmp_path, cloud):
    monkeypatch.setenv("EVAL_TEST_KEY","test-key")
    monkeypatch.setattr(sys,"argv",["evals.run","--provider","cloud","--model","selected-model",
        "--base-url","https://model.example","--api-key-env","EVAL_TEST_KEY","--output",str(tmp_path)])
    main()
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["dataset_version"] == "exercise-live-v1"
    assert report["case_count"] == 7 and len(report["rows"]) == 21
    assert "selected-model" in (tmp_path / "report.md").read_text()
    assert cloud[0]["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in json.dumps(report)
