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
