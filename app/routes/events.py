from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.redis_client import check_idempotency
from app.queue import push_to_queue

router = APIRouter(prefix="/events", tags=["events"])


class IngestEventBody(BaseModel):
    event_id: str = Field(..., description="Unique idempotency key for this event")
    source: str = Field(default="order_updates", description="e.g. order_updates, iot, logs")
    payload: dict = Field(default_factory=dict, description="Raw event payload")


@router.post("/ingest")
async def ingest_event(body: IngestEventBody) -> JSONResponse:
    """
    Accept an event/order update. Idempotent: same event_id twice -> 200 (already processed).
    New event -> 202 Accepted (queue will be added next; we only validate + idempotency).
    """
    idempotency_key = f"idempotency:{body.event_id}"
    is_duplicate = await check_idempotency(idempotency_key)

    if is_duplicate:
        return JSONResponse(
            status_code=200,
            content={"status": "already_processed", "event_id": body.event_id},
        )

    await push_to_queue(body.event_id, body.source, body.payload)
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "event_id": body.event_id},
    )
