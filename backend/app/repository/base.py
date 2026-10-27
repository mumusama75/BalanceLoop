"""Repository interface (class diagram «interface» Repository).

Agents depend only on this contract; ``VersionedRecordStore`` realises it on SQLAlchemy.
Method names follow the class diagram where the operation exists there.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AuditStoreError(Exception):
    """Raised when an audit record cannot be persisted — the system must fail closed (AR-10)."""


class Repository(ABC):
    # --- audit (AR-10)
    @abstractmethod
    def append_audit(self, request_id: str, user_id: Optional[str], actor: str, action: str, *,
                     decision: Optional[str] = None, versions: Optional[Dict[str, Any]] = None,
                     payload: Optional[Dict[str, Any]] = None) -> str: ...

    # --- UC01
    @abstractmethod
    def save_profile(self, user_id: str, data: Dict[str, Any], status: str, missing_fields: List[str],
                     conflicts: List[str]) -> Any: ...
    @abstractmethod
    def reload_profile(self, user_id: str) -> Any: ...
    @abstractmethod
    def record_consent(self, user_id: str, scope: str, granted: bool, profile_version: Optional[int]) -> Any: ...
    @abstractmethod
    def withdraw_consent(self, user_id: str, scope: str) -> Any: ...
    @abstractmethod
    def consents(self, user_id: str) -> Dict[str, bool]: ...

    # --- UC02
    @abstractmethod
    def save_food_entry(self, entry: Any) -> Any: ...

    # --- UC05 / UC06
    @abstractmethod
    def save_assessment(self, assessment: Any) -> Any: ...
    @abstractmethod
    def reload_latest_readiness(self, user_id: str, usable_only: bool = True) -> Any: ...
    @abstractmethod
    def save_candidate(self, candidate: Any) -> Any: ...

    # --- UC09 / UC10
    @abstractmethod
    def find_accepted_counterpart(self, user_id: str, plan_date: Any, kind: str) -> Any: ...
    @abstractmethod
    def load_policy(self, version: Optional[str] = None) -> Any: ...
