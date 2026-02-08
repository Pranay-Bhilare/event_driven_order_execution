from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.metrics import events_ingested_total
from app.queue import push_to_queue
from app.redis_client import check_idempotency

router = APIRouter(prefix="/events", tags=["events"])

OrderEventType = Literal[
    "ORDER_CREATED",
    "PAYMENT_CONFIRMED",
    "ORDER_SHIPPED",
    "ORDER_DELIVERED",
]


class IngestEventBody(BaseModel):
    event_id: str = Field(..., description="Unique idempotency key for this event")
    order_id: str = Field(..., description="Order this event belongs to")
    event_type: OrderEventType = Field(..., description="Order lifecycle event type")
    event_version: int = Field(default=1, description="Schema version of the event")
    payload: dict = Field(default_factory=dict, description="Event payload")


@router.post("/ingest")
async def ingest_event(body: IngestEventBody) -> JSONResponse:
    """
    Accept an order lifecycle event. Idempotent: same event_id twice -> 200 (already processed).
    New event -> 202 Accepted.
    """
    idempotency_key = f"idempotency:{body.event_id}"
    is_duplicate = await check_idempotency(idempotency_key)

    if is_duplicate:
        return JSONResponse(
            status_code=200,
            content={"status": "already_processed", "event_id": body.event_id},
        )

    await push_to_queue(
        event_id=body.event_id,
        order_id=body.order_id,
        event_type=body.event_type,
        event_version=body.event_version,
        payload=body.payload,
    )
    events_ingested_total.labels(event_type=body.event_type).inc()
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "event_id": body.event_id},
    )
