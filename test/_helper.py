"""
Shared helpers for scenario test scripts.
Uses: API_URL, DATABASE_URL, REDIS_URL from env (defaults for local docker).
"""
import json
import os
import urllib.request

# Defaults for local docker compose
API_BASE = os.environ.get("API_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ingestion")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def ingest_event(
    event_id: str,
    order_id: str,
    event_type: str,
    event_version: int = 1,
    payload: dict | None = None,
    api_base: str | None = None,
) -> tuple[int, dict]:
    """POST one event to /events/ingest. Returns (status_code, response_body). Never raises on HTTP error."""
    base = api_base or API_BASE
    body = {
        "event_id": event_id,
        "order_id": order_id,
        "event_type": event_type,
        "event_version": event_version,
        "payload": payload or {},
    }
    req = urllib.request.Request(
        f"{base}/events/ingest",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()) if e.read() else {}


async def fetch_events_for_order(order_id: str, database_url: str | None = None) -> list[str]:
    """Return list of event_type for order_id, ordered by created_at (oldest first)."""
    import asyncpg
    url = database_url or DATABASE_URL
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT event_type FROM ingestion_events
            WHERE order_id = $1
            ORDER BY created_at ASC;
            """,
            order_id,
        )
        return [r["event_type"] for r in rows]
    finally:
        await conn.close()


def get_dlq_length(redis_url: str | None = None) -> int:
    """Return current length of Redis DLQ (queue:ingestion_events:dlq)."""
    import redis
    url = redis_url or REDIS_URL
    r = redis.from_url(url, decode_responses=True)
    return r.llen("queue:ingestion_events:dlq")
