"""Small shared helpers: ids and timestamps."""
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    """Readable unique id such as ``prof_3f9a1c2b7d4e``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
