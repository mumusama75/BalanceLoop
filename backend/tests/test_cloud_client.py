"""Offline HTTP contracts for the real cloud gateway; no credentials or live API calls."""
from copy import deepcopy

import httpx
import pytest
from pydantic import BaseModel

from app.llm.cloud_client import CloudLLMClient
from app.llm.gateway import LLMUnavailable


class Reply(BaseModel):
    count: int


def envelope(content='{"count": 2}', **extra):
    return {"choices": [{"message": {"content": content}}], **extra}


@pytest.fixture
def gateway(monkeypatch):
    responses, calls = [], []

    def post(url, **kwargs):
        calls.append((url, deepcopy(kwargs)))
        assert responses, "unexpected extra HTTP request"
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return CloudLLMClient("https://model.example/v1", "test-key", "test-model"), responses, calls


def run(client):
    return client.complete("Return JSON", "input", Reply)


def test_success_and_request_contract(gateway):
    client, responses, calls = gateway
    responses.append((200, envelope(usage={"total_tokens": 12})))
    assert run(client).count == 2
    url, args = calls[0]
    assert url == "https://model.example/v1/chat/completions"
    assert args["headers"]["Authorization"] == "Bearer test-key"
    assert args["timeout"] == 60
    assert args["json"]["response_format"] == {"type": "json_object"}
    assert '"count"' in args["json"]["messages"][0]["content"]
    assert client.last_meta["usage"]["total_tokens"] == 12


@pytest.mark.parametrize("body", [None, [], {}, {"choices": []}, {"choices": None},
    {"choices": [None]}, {"choices": [{}]}, {"choices": [{"message": None}]},
    envelope(None), envelope([]), envelope(""), envelope("   ")])
def test_malformed_envelope_fails_without_correction(gateway, body):
    client, responses, calls = gateway
    responses.append((200, body))
    with pytest.raises(LLMUnavailable):
        run(client)
    assert len(calls) == 1
    assert client.last_meta == {}


@pytest.mark.parametrize("content", ['not json', '{"count":"invalid"}'])
def test_one_corrective_retry(gateway, content):
    client, responses, calls = gateway
    responses.extend([(200, envelope(content)), (200, envelope())])
    assert run(client).count == 2
    assert len(calls) == 2
    messages = calls[1][1]["json"]["messages"]
    assert messages[-2] == {"role": "assistant", "content": content}
    assert messages[-1]["role"] == "user"


def test_invalid_output_exhausts_budget_without_exposing_content(gateway):
    client, responses, calls = gateway
    responses.extend([(200, envelope('{"count":"private-payload"}'))] * 2)
    with pytest.raises(LLMUnavailable) as error:
        run(client)
    assert "private-payload" not in str(error.value)
    assert len(calls) == 2
    assert client.last_meta == {}


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_http_errors_fail_closed_without_retry(gateway, status):
    client, responses, calls = gateway
    responses.append((status, {"error": "private-payload"}))
    with pytest.raises(LLMUnavailable) as error:
        run(client)
    assert str(status) in str(error.value)
    assert "private-payload" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_errors_clear_previous_metadata(gateway, error_type):
    client, responses, calls = gateway
    responses.extend([(200, envelope()), error_type("private-payload")])
    run(client)
    with pytest.raises(LLMUnavailable) as error:
        run(client)
    assert "private-payload" not in str(error.value)
    assert client.last_meta == {}
    assert len(calls) == 2


def test_json_mode_fallback_still_validates_schema(gateway):
    client, responses, calls = gateway
    responses.extend([(400, {"error": "response_format unsupported"}),
                      (200, envelope("bad JSON")), (200, envelope())])
    assert run(client).count == 2
    assert len(calls) == 3
    assert "response_format" not in calls[1][1]["json"]
    assert "response_format" not in calls[2][1]["json"]


def test_missing_key_does_not_send_request(gateway):
    client, _, calls = gateway
    client.api_key = ""
    with pytest.raises(LLMUnavailable):
        run(client)
    assert not calls


def test_markdown_fenced_json(gateway):
    client, responses, _ = gateway
    responses.append((200, envelope('```json\n{"count":2}\n```')))
    assert run(client).count == 2


def test_non_json_http_body_is_provider_failure(gateway, monkeypatch):
    client, _, calls = gateway
    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, text="<html>upstream error</html>",
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(LLMUnavailable):
        run(client)
    assert len(calls) == 1


def traced(client, request_id="req-test"):
    from app.llm.telemetry import TracedGateway
    from app.services.trace import Trace
    trace = Trace(request_id, "test-user")
    return TracedGateway(client, trace, "TestAgent"), trace


def test_trace_counts_all_attempts_and_partial_usage(gateway, monkeypatch):
    from app.llm import telemetry
    ticks = iter([0, 1, 2, 3, 4, 5, 6, 7])
    monkeypatch.setattr(telemetry, "monotonic", lambda: next(ticks))
    client, responses, _ = gateway
    responses.extend([(400, {"error": "response_format unsupported"}),
        (200, envelope("invalid", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})),
        (200, envelope(usage={"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24}))])
    proxy, trace = traced(client)
    assert run(proxy).count == 2
    assert len(trace.steps) == 1
    span = trace.steps[0]
    assert span.agent == "TestAgent" and span.model_version == client.model_version
    d = span.detail
    assert d["request_id"] == "req-test" and d["operation"] == "complete"
    assert d["latency_ms"] == 7000
    assert d["retry_count"] == 2 and d["attempt_count"] == 3
    assert [a["latency_ms"] for a in d["attempts"]] == [1000, 1000, 1000]
    assert [a["status_code"] for a in d["attempts"]] == [400, 200, 200]
    assert d["usage"] == {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36}
    assert not any(d["usage_complete"].values())


@pytest.mark.parametrize("outcome", [httpx.ReadTimeout("private-payload"),
    (429, {"error": "private-payload"}), (200, {"choices": []})])
def test_failed_calls_are_traced_and_isolated_from_next_call(gateway, outcome):
    client, responses, _ = gateway
    responses.extend([outcome, (200, envelope(usage={"total_tokens": 8}))])
    proxy, trace = traced(client)
    with pytest.raises(LLMUnavailable):
        run(proxy)
    run(proxy)
    failed, success = [s.detail for s in trace.steps]
    assert failed["status"] == "error" and failed["error_type"] == "LLMUnavailable"
    assert failed["usage"]["total_tokens"] is None
    assert failed["attempt_count"] == 1 and failed["retry_count"] == 0
    assert success["usage"]["total_tokens"] == 8
    assert success["usage_complete"]["total_tokens"] is True
    assert success["attempt_count"] == 1 and success["status"] == "success"
    assert failed["call_id"] != success["call_id"]
    assert "private-payload" not in str(trace.as_list())
    assert "test-key" not in str(trace.as_list())


def test_exhausted_repair_keeps_usage_from_both_invalid_outputs(gateway):
    client, responses, _ = gateway
    responses.extend([(200, envelope("bad", usage={"total_tokens": 7}))] * 2)
    proxy, trace = traced(client)
    with pytest.raises(LLMUnavailable):
        run(proxy)
    d = trace.steps[0].detail
    assert d["status"] == "error" and d["retry_count"] == 1
    assert d["usage"]["total_tokens"] == 14
    assert d["usage_complete"]["total_tokens"] is True


def test_missing_key_records_zero_attempts_and_unknown_usage(gateway):
    client, _, _ = gateway
    client.api_key = ""
    proxy, trace = traced(client)
    with pytest.raises(LLMUnavailable):
        run(proxy)
    d = trace.steps[0].detail
    assert d["attempt_count"] == 0 and d["retry_count"] == 0
    assert d["usage"]["total_tokens"] is None


@pytest.mark.parametrize("usage", [None, [], {"total_tokens": -1}, {"total_tokens": True},
    {"total_tokens": "secret", "unexpected": "private-payload"}])
def test_usage_metadata_is_allowlisted(gateway, usage):
    client, responses, _ = gateway
    responses.append((200, envelope(usage=usage)))
    proxy, trace = traced(client)
    assert run(proxy).count == 2
    assert trace.steps[0].detail["usage"]["total_tokens"] is None
    assert "private-payload" not in str(trace.as_list())


def test_concurrent_requests_on_shared_gateway_do_not_mix_metrics(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    client = CloudLLMClient("https://model.example", "test-key", "test-model")

    def post(url, **kwargs):
        count = int(kwargs["json"]["messages"][1]["content"])
        barrier.wait(timeout=5)
        return httpx.Response(200, json=envelope(usage={"total_tokens": count}),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    def request(count):
        proxy, trace = traced(client, f"req-{count}")
        proxy.complete("Return JSON", str(count), Reply)
        return trace.steps[0].detail

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(request, [11, 22]))
    assert [d["request_id"] for d in records] == ["req-11", "req-22"]
    assert [d["usage"]["total_tokens"] for d in records] == [11, 22]
    assert all(d["attempt_count"] == 1 for d in records)


def test_direct_call_after_traced_call_does_not_append_to_old_span(gateway):
    client, responses, _ = gateway
    responses.extend([(200, envelope()), (200, envelope())])
    proxy, trace = traced(client)
    run(proxy)
    before = deepcopy(trace.steps[0].detail)
    run(client)
    assert trace.steps[0].detail == before
