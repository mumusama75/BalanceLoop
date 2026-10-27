"""ExternalDataSource interface (class diagram «interface» ExternalDataSource)."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ExternalDataSource(ABC):
    version: str = "unknown"

    @abstractmethod
    def fetch_nutrition_data(self, query: str) -> Optional[Dict[str, Any]]:
        """Return the nutrition record matching *query* or None (UC02)."""

    def import_wearable_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Optional feature O2 — not implemented in the prototype; readiness works without it."""
        return None
