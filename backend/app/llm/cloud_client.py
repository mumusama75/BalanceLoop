"""CloudLLMClient — OpenAI-compatible chat/completions client (DeepSeek, OpenAI, Qwen, Ollama…).

Only de-identified input is sent (see ``gateway.deidentify``). Replies must be JSON
matching the requested schema; one corrective retry is attempted, then LLMUnavailable.
"""
from __future__ import annotations

import json
import time
from typing import Type, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from .gateway import LLMGateway, LLMUnavailable
from .telemetry import post_with_metrics

T = TypeVar("T", bound=BaseModel)


class CloudLLMClient(LLMGateway):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.base_url = self.normalise_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        host = urlparse(base_url).netloc or base_url
        self.model_version = f"{model}@{host}"
        self.last_meta = {}
        self._json_mode = True   # switched off automatically if the server rejects response_format

    @staticmethod
    def normalise_base_url(url: str) -> str:
        """Accept any of  https://host  ·  https://host/v1  ·  https://host/v1/chat/completions  → https://host/v1"""
        u = url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/completions"):
            if u.endswith(suffix):
                u = u[: -len(suffix)]
        if not u.rstrip("/").endswith("/v1"):
            u = u.rstrip("/") + "/v1"
        return u

    def _strip_fences(self, text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else t[3:]
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip()

    def complete(self, system: str, user: str, schema: Type[T]) -> T:
        self.last_meta = {}
        if not self.api_key:
            raise LLMUnavailable("no API key configured")
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": f"{system}\n\nJSON Schema for your reply:\n{schema_json}"},
            {"role": "user", "content": user},
        ]
        for attempt in range(2):
            started = time.monotonic()
            try:
                body_out = {"model": self.model, "messages": messages, "temperature": 0.3}
                if self._json_mode:
                    body_out["response_format"] = {"type": "json_object"}
                resp = post_with_metrics(f"{self.base_url}/chat/completions",
                                  headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                  json=body_out, timeout=self.timeout)
                if resp.status_code == 400 and self._json_mode and "response_format" in resp.text:
                    # self-hosted servers (older vLLM / Ollama) may not support JSON mode; the prompt still demands JSON
                    self._json_mode = False
                    resp = post_with_metrics(f"{self.base_url}/chat/completions",
                                      headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                      json={"model": self.model, "messages": messages, "temperature": 0.3}, timeout=self.timeout)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise LLMUnavailable(f"provider HTTP {e.response.status_code}") from None
            except httpx.HTTPError as e:
                # Do not expose URLs, response bodies or provider exception text to traces/users.
                raise LLMUnavailable(f"provider transport failure ({type(e).__name__})") from None

            try:
                body = resp.json()
                if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
                    raise ValueError("invalid envelope")
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("missing text content")
            except (ValueError, KeyError, IndexError, TypeError):
                # Invalid provider envelopes are not model output that a corrective prompt can fix.
                raise LLMUnavailable("invalid provider response: expected non-empty message content") from None

            try:
                data = json.loads(self._strip_fences(content))
                result = schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                if attempt == 1:
                    raise LLMUnavailable("model output failed schema validation after 2 attempts") from None
                # ValidationError.__str__ includes input values; do not copy them into diagnostics.
                reason = "invalid JSON" if isinstance(e, json.JSONDecodeError) else "schema mismatch"
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"That reply did not validate against the schema ({reason}). "
                                                            f"Return ONLY a corrected JSON object."})
                continue
            self.last_meta = {"latency_ms": int((time.monotonic() - started) * 1000),
                              "usage": body.get("usage", {}), "attempt": attempt + 1}
            return result
        raise LLMUnavailable("model output unavailable")  # defensive: loop always returns or raises
