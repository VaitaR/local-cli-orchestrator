"""Correlation and step-id utilities for observability."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class CorrelationIds:
    """Correlation IDs for a single operation."""

    call_id: str
    span_id: str
    parent_id: str | None = None


class StepCounter:
    """Thread-safe step counter with optional persistence callback."""

    def __init__(
        self,
        *,
        start_at: int = 0,
        persist: Callable[[int], None] | None = None,
    ) -> None:
        self._value = start_at
        self._persist = persist
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        """Current counter value."""
        with self._lock:
            return self._value

    def next(self) -> int:
        """Increment and return the next step id."""
        with self._lock:
            self._value += 1
            value = self._value
        if self._persist:
            self._persist(value)
        return value


def new_id() -> str:
    """Return a random identifier string."""
    return uuid.uuid4().hex


def new_correlation(parent_id: str | None = None) -> CorrelationIds:
    """Create call/span correlation identifiers."""
    return CorrelationIds(call_id=new_id(), span_id=new_id(), parent_id=parent_id)
