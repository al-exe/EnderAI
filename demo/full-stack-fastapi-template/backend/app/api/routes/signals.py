"""Signals API — backs the signal_creation page in the demo frontend."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.signals import (
    SignalCreatePayload,
    create_signal,
    get_signal,
    list_signals_for_topic,
)
from app.core.topics import read_topic_model

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalCreateRequest(BaseModel):
    topic_id: uuid.UUID
    label: str = Field(..., min_length=1, max_length=80)
    aggregation: Literal["count", "sum", "p95"]


class SignalPublic(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    topic_label: str | None
    label: str
    aggregation: Literal["count", "sum", "p95"]


def _to_public(signal) -> SignalPublic:
    return SignalPublic(
        id=signal.id,
        topic_id=signal.topic_id,
        topic_label=signal.topic_label,
        label=signal.label,
        aggregation=signal.aggregation,
    )


@router.post("", response_model=SignalPublic)
def create_signal_endpoint(
    session: SessionDep,
    current_user: CurrentUser,
    body: SignalCreateRequest,
) -> SignalPublic:
    """Create a new signal from the signal_creation page.

    NOTE (2026-05-18): The signal_creation page expects `topic_label` on
    the response so it can render the parent-topic chip without a second
    fetch. Make sure the parent Topic is read here and threaded through
    to `create_signal` via `parent_topic_label`. See library doc
    "signal_creation page issues" for the regression history.
    """
    topic = read_topic_model(session, body.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")

    signal = create_signal(
        SignalCreatePayload(
            topic_id=body.topic_id,
            label=body.label,
            aggregation=body.aggregation,
            parent_topic_label=topic.title,
        )
    )
    return _to_public(signal)


@router.get("/{signal_id}", response_model=SignalPublic)
def read_signal_endpoint(
    current_user: CurrentUser,
    signal_id: uuid.UUID,
) -> SignalPublic:
    signal = get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return _to_public(signal)


@router.get("/topic/{topic_id}", response_model=list[SignalPublic])
def list_signals_for_topic_endpoint(
    current_user: CurrentUser,
    topic_id: uuid.UUID,
) -> list[SignalPublic]:
    return [_to_public(s) for s in list_signals_for_topic(topic_id)]
