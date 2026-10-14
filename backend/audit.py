"""Append-only audit trail for agent-loop events (output/audit_trail.json).

The file is a JSON array of AuditEvent objects. Each append reads the current
array, checks it is valid, adds the new event at the end, and atomically
replaces the file (write temp + os.replace), so a crash never leaves a
half-written file and earlier events are never dropped. If the existing file
is not a valid audit array, appending fails loudly instead of overwriting it.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import AuditEvent

DEFAULT_AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"

# Credential-like keys only: usage counters such as `total_tokens` must stay visible.
SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|password|authorization|credential|bearer|(access|auth|refresh|session)[_-]?token)", re.I
)
MAX_STRING_CHARS = 4000


class AuditTrailCorrupt(RuntimeError):
    """The audit file exists but is not a JSON array; refuse to touch it."""


def sanitize(value: Any) -> Any:
    """Drop secrets and trim very long strings before anything is written."""
    secret = os.environ.get("PORTKEY_API_KEY")
    if isinstance(value, dict):
        return {
            str(k): "[redacted]" if SENSITIVE_KEY.search(str(k)) else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        if secret and secret in value:
            value = value.replace(secret, "[redacted]")
        if len(value) > MAX_STRING_CHARS:
            value = value[:MAX_STRING_CHARS] + f"... [truncated {len(value) - MAX_STRING_CHARS} chars]"
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return sanitize(str(value))


class AuditTrail:
    def __init__(self, path: Path = DEFAULT_AUDIT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        try:
            events = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AuditTrailCorrupt(f"{self.path} is not valid JSON; not appending ({exc})") from exc
        if not isinstance(events, list):
            raise AuditTrailCorrupt(f"{self.path} must hold a JSON array of events")
        return events

    def append(self, event: AuditEvent) -> AuditEvent:
        record = json.loads(event.model_dump_json())
        record["data"] = sanitize(record["data"])
        record["summary"] = sanitize(record["summary"])
        with self._lock:
            events = self.read()
            events.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        return event

    def log(
        self,
        *,
        run_id: str,
        run_type: str,
        ticket_id: int | None,
        agent: str | None,
        event_type: str,
        summary: str,
        data: dict | None = None,
        depth: int | None = None,
        chain: list[str] | None = None,
        step: int | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            run_type=run_type,
            ticket_id=ticket_id,
            agent=agent,
            depth=depth,
            chain=chain or [],
            step=step,
            event_type=event_type,
            summary=summary,
            data=data or {},
        )
        return self.append(event)
