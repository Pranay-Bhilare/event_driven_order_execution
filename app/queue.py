"""
Push event payload to Redis queue (LPUSH). Worker pulls with BRPOP.
Queue key: queue:ingestion_events
"""
import json
from app.redis_client import get_redis

INGESTION_QUEUE_KEY = "queue:ingestion_events"
INGESTION_DLQ_KEY = "queue:ingestion_events:dlq"


async def push_to_queue(event_id: str, source: str, payload: dict) -> None:
    r = await get_redis()
    message = json.dumps({
        "event_id": event_id,
        "source": source,
        "payload": payload,
        "attempts": 0,
    })
    await r.lpush(INGESTION_QUEUE_KEY, message)
