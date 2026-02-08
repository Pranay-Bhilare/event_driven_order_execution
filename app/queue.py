"""
Push order lifecycle event to queue. Backend: Redis (LPUSH) or AWS SQS when SQS_QUEUE_URL is set.
"""
import json

from app.config import settings
from app.redis_client import get_redis
from app.sqs_client import send_message

INGESTION_QUEUE_KEY = "queue:ingestion_events"
INGESTION_DLQ_KEY = "queue:ingestion_events:dlq"


def _make_body(
    event_id: str,
    order_id: str,
    event_type: str,
    event_version: int,
    payload: dict,
    attempts: int = 0,
) -> dict:
    return {
        "event_id": event_id,
        "order_id": order_id,
        "event_type": event_type,
        "event_version": event_version,
        "payload": payload,
        "attempts": attempts,
    }


async def push_to_queue(
    event_id: str,
    order_id: str,
    event_type: str,
    event_version: int,
    payload: dict,
    attempts: int = 0,
) -> None:
    body = _make_body(event_id, order_id, event_type, event_version, payload, attempts)
    if settings.sqs_queue_url:
        await send_message(body)
    else:
        r = await get_redis()
        await r.lpush(INGESTION_QUEUE_KEY, json.dumps(body))
