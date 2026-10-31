"""Request-owned model spans. Context variables isolate concurrent HTTP attempt collectors."""
from contextvars import ContextVar
from functools import wraps
from time import monotonic

import httpx

from ..util import new_id

_attempts = ContextVar("llm_attempts", default=None)
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def post_with_metrics(url, **kwargs):
    """Record only allowlisted metadata, never prompts, credentials or response bodies."""
    started = monotonic()
    record = {"status_code": None, "error_type": None,
              "usage": {key: None for key in TOKEN_FIELDS}}
    try:
        response = httpx.post(url, **kwargs)
        record["status_code"] = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        usage = body.get("usage") if isinstance(body, dict) else None
        if isinstance(usage, dict):
            for key in TOKEN_FIELDS:
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    record["usage"][key] = value
        return response
    except BaseException as error:
        # Observe interruptions too, but always propagate them to the caller.
        record["error_type"] = type(error).__name__
        raise
    finally:
        record["latency_ms"] = round((monotonic() - started) * 1000, 3)
        collector = _attempts.get()
        if collector is not None:
            record["attempt"] = len(collector) + 1
            collector.append(record)


class TracedGateway:
    """Proxy scoped to an agent/request; works for cloud methods and offline mock overrides."""

    def __init__(self, gateway, trace, agent):
        self.gateway, self.trace, self.agent = gateway, trace, agent

    def __getattr__(self, name):
        target = getattr(self.gateway, name)
        if not callable(target) or name.startswith("_"):
            return target

        @wraps(target)
        def call(*args, **kwargs):
            attempts = []
            token = _attempts.set(attempts)
            started = monotonic()
            status, error_type = "success", None
            try:
                return target(*args, **kwargs)
            except BaseException as error:
                status, error_type = "error", type(error).__name__
                raise
            finally:
                elapsed = round((monotonic() - started) * 1000, 3)
                _attempts.reset(token)
                # Null means unknown, not zero; partial sums are explicitly identified.
                usage, complete = {}, {}
                for key in TOKEN_FIELDS:
                    values = [a["usage"][key] for a in attempts if a["usage"][key] is not None]
                    usage[key] = sum(values) if values else None
                    complete[key] = bool(attempts) and len(values) == len(attempts)
                detail = {"call_id": new_id("llm"), "request_id": self.trace.request_id,
                          "operation": name, "status": status, "error_type": error_type,
                          "latency_ms": elapsed, "attempt_count": len(attempts),
                          "retry_count": max(0, len(attempts) - 1),
                          "usage": usage, "usage_complete": complete, "attempts": attempts,
                          "mock": self.gateway.model_version.startswith("mock-")}
                self.trace.add(self.agent, "llmCall", f"{name}: {status}; {elapsed} ms; "
                               f"{detail['retry_count']} retries", llm_used=True,
                               model_version=self.gateway.model_version, detail=detail)
        return call
