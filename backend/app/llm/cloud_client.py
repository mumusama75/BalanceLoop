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
        if not self.api_key:
            raise LLMUnavailable("no API key configured")
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": f"{system}\n\nJSON Schema for your reply:\n{schema_json}"},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        content = ""
        for attempt in range(2):
            started = time.time()
            try:
                body_out = {"model": self.model, "messages": messages, "temperature": 0.3}
                if self._json_mode:
                    body_out["response_format"] = {"type": "json_object"}
                resp = httpx.post(f"{self.base_url}/chat/completions",
                                  headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                  json=body_out, timeout=self.timeout)
                if resp.status_code == 400 and self._json_mode and "response_format" in resp.text:
                    # self-hosted servers (older vLLM / Ollama) may not support JSON mode; the prompt still demands JSON
                    self._json_mode = False
                    resp = httpx.post(f"{self.base_url}/chat/completions",
                                      headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                      json={"model": self.model, "messages": messages, "temperature": 0.3}, timeout=self.timeout)
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                self.last_meta = {"latency_ms": int((time.time() - started) * 1000),
                                  "usage": body.get("usage", {}), "attempt": attempt + 1}
                data = json.loads(self._strip_fences(content))
                return schema.model_validate(data)
            except (httpx.HTTPError, KeyError) as e:
                last_error = e
                break  # transport problems: do not retry with a correction, fail over
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"That reply did not validate against the schema: {e}. "
                                                            f"Return ONLY a corrected JSON object."})
        raise LLMUnavailable(f"{type(last_error).__name__}: {last_error}")
