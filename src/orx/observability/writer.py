"""Thread-safe writer for observability events and bundle metadata."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from orx.observability.schema import ObsEvent


class EventWriter:
    """Append-only JSONL writer for observability events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, event: ObsEvent) -> None:
        """Append one event entry to the timeline."""
        payload = event.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True))
                handle.write("\n")

    def read_all(self) -> list[dict[str, Any]]:
        """Read and parse all events from the timeline."""
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                events.append(data)
        return events


class MetadataWriter:
    """Writer for observability metadata.json."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, data: dict[str, Any]) -> None:
        """Overwrite metadata file atomically enough for local usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read(self) -> dict[str, Any]:
        """Read metadata content if available, otherwise return empty dict."""
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(raw, dict):
            return raw
        return {}
