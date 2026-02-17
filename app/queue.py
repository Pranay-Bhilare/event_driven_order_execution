"""
Push order lifecycle event to SQS. SQS only.
"""
import json

from app.config import settings
from app.sqs_client import send_message


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
    if not settings.sqs_queue_url:
        raise RuntimeError("SQS_QUEUE_URL is required")
    body = _make_body(event_id, order_id, event_type, event_version, payload, attempts)
    await send_message(body)
