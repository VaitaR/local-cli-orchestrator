"""TTY recording utilities (best-effort) for observability bundles."""

from __future__ import annotations

import json
import shutil
import threading
import time
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
        self.capture_mode = "synthetic"
        self.reason: str | None = None
        self._start_monotonic: float | None = None
        self._lock = threading.Lock()

    def start(self) -> tuple[bool, str | None]:
        """Initialize cast file and return `(enabled, reason_if_disabled)`."""
        self._start_monotonic = time.perf_counter()
        asciinema_bin = shutil.which("asciinema")
        self.capture_mode = (
            "asciinema_passive" if asciinema_bin is not None else "synthetic"
        )

        header = {
            "version": 2,
            "width": 120,
            "height": 40,
            "timestamp": int(datetime.now(tz=UTC).timestamp()),
            "env": {"SHELL": "orx", "TERM": "xterm-256color"},
            "title": "orx observability tty",
            "capture_mode": self.capture_mode,
            "asciinema_available": bool(asciinema_bin),
        }

        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(json.dumps(header) + "\n", encoding="utf-8")
            self.enabled = True
            self.reason = None
        except OSError:
            self.enabled = False
            self.reason = "tty_output_init_failed"
        return self.enabled, self.reason

    def note(self, message: str) -> None:
        """Append a synthetic output frame to cast file."""
        if not self.output_path.exists():
            return
        elapsed = 0.0
        if self._start_monotonic is not None:
            elapsed = max(0.0, time.perf_counter() - self._start_monotonic)
        frame = [
            round(elapsed, 3),
            "o",
            message.rstrip("\n") + "\n",
        ]
        with self._lock, self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(frame, ensure_ascii=True))
            handle.write("\n")
