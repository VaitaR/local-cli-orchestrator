"""TTY recording utilities (best-effort) for observability bundles."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


class TTYRecorder:
    """Best-effort TTY recorder.

    For portability in local runs, we create a valid asciinema v2 cast file.
    If asciinema is available we note it in the header, but we keep recording
    passive to avoid wrapping the full process tree.
    """

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.enabled = False
        self.reason: str | None = None

    def start(self) -> tuple[bool, str | None]:
        """Initialize cast file and return `(enabled, reason_if_disabled)`."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        asciinema_bin = shutil.which("asciinema")

        header = {
            "version": 2,
            "width": 120,
            "height": 40,
            "timestamp": int(datetime.now(tz=UTC).timestamp()),
            "env": {"SHELL": "orx", "TERM": "xterm-256color"},
            "title": "orx observability tty",
            "asciinema_available": bool(asciinema_bin),
        }

        self.output_path.write_text(json.dumps(header) + "\n", encoding="utf-8")

        self.enabled = True
        if asciinema_bin is None:
            self.reason = "asciinema_not_found"
        else:
            self.reason = None
        return self.enabled, self.reason

    def note(self, message: str) -> None:
        """Append a synthetic output frame to cast file."""
        if not self.output_path.exists():
            return
        frame = [
            round(datetime.now(tz=UTC).timestamp(), 3),
            "o",
            message.rstrip("\n") + "\n",
        ]
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(frame, ensure_ascii=True))
            handle.write("\n")
