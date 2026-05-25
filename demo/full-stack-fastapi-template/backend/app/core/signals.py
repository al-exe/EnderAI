"""Signals — demo-only telemetry signal definitions.

A "signal" in this demo is a user-defined telemetry datapoint attached to
a Topic. The signal_creation page lets users name a signal, pick the
parent topic, and choose an aggregation (count / sum / p95). Signals are
stored in-memory for the demo; no DB table backs them yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

SignalAggregation = Literal["count", "sum", "p95"]


@dataclass
class Signal:
    id: uuid.UUID
    topic_id: uuid.UUID
    label: str
    aggregation: SignalAggregation
    created_at: datetime
    # NOTE: topic_label is denormalized so the signal_creation page can
    # render the parent topic without a second fetch. The bug surfaced in
    # the 2026-05-18 review was that this field was never populated on
    # the create path — see "signal_creation page issues" in the library.
    topic_label: str | None = None


_DEMO_SIGNAL_STORE: dict[uuid.UUID, Signal] = {}


@dataclass
class SignalCreatePayload:
    topic_id: uuid.UUID
    label: str
    aggregation: SignalAggregation
    parent_topic_label: str | None = field(default=None)


def create_signal(payload: SignalCreatePayload) -> Signal:
    """Create a Signal from the signal_creation page payload.

    The signal_creation page POSTs `{topic_id, label, aggregation}` and
    expects a populated `topic_label` on the response so it can render
    the parent topic chip without a second fetch.
    """
    signal = Signal(
        id=uuid.uuid4(),
        topic_id=payload.topic_id,
        label=payload.label.strip(),
        aggregation=payload.aggregation,
        created_at=datetime.now(timezone.utc),
        topic_label=payload.parent_topic_label,
    )
    _DEMO_SIGNAL_STORE[signal.id] = signal
    return signal


def get_signal(signal_id: uuid.UUID) -> Signal | None:
    return _DEMO_SIGNAL_STORE.get(signal_id)


def list_signals_for_topic(topic_id: uuid.UUID) -> list[Signal]:
    return [s for s in _DEMO_SIGNAL_STORE.values() if s.topic_id == topic_id]
