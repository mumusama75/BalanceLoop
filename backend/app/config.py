"""Application settings.

All values can be overridden through environment variables prefixed with ``BL_``
or through ``backend/.env`` (git-ignored).
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent   # …/BalanceLoop/backend


class Settings(BaseSettings):
    # .env lives next to this package (backend/.env) so it is found from any working directory
    model_config = SettingsConfigDict(env_prefix="BL_", env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'balanceloop.db'}"

    # LLM gateway
    llm_provider: str = "mock"  # "cloud" | "mock"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0

    # Safety Supervisor requires this review-policy version; anything else fails closed.
    required_policy_version: str = "1.0"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # On an empty database, also run a scripted day for the demo user Sam (offline mock LLM) so every page has data.
    seed_demo_flow: bool = True

    # Prototype rule version identifiers (recorded in every assessment / decision)
    readiness_rule_version: str = "readiness-rules-1.0"
    hard_rule_version: str = "hard-rules-1.0"

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite(cls, v: str) -> str:
        """A relative SQLite path (e.g. ``sqlite:///./balanceloop.db`` from .env) is resolved against backend/,
        so the same file is used whether the server is started from the repo root, backend/ or an IDE."""
        prefix = "sqlite:///"
        if v.startswith(prefix) and not v.startswith("sqlite:////") and not v.startswith(prefix + ":memory:"):
            return prefix + str((BACKEND_DIR / v[len(prefix):]).resolve())
        return v

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
