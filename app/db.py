"""
Async Postgres access for the worker (asyncpg). Order lifecycle events.
Table has UNIQUE(idempotency_key) so duplicate inserts raise UniqueViolationError.
"""
import json
import uuid
import asyncpg
from asyncpg.exceptions import UniqueViolationError

from app.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=5,
            command_timeout=60,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS ingestion_events;")
        await conn.execute("""
            CREATE TABLE ingestion_events (
                id UUID PRIMARY KEY,
                idempotency_key VARCHAR(255) NOT NULL,
                order_id VARCHAR(255) NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                event_version INT NOT NULL DEFAULT 1,
                payload JSONB,
                status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
                attempts INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(idempotency_key)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_events_order_id
            ON ingestion_events(order_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_events_event_type
            ON ingestion_events(event_type);
        """)


async def insert_event(
    pool: asyncpg.Pool,
    event_id: str,
    order_id: str,
    event_type: str,
    event_version: int,
    payload: dict,
) -> bool:
    """
    Insert one order lifecycle event. Returns True if inserted, False if duplicate.
    """
    row_id = uuid.uuid4()
    idempotency_key = event_id
    status = "COMPLETED"
    payload_json = json.dumps(payload) if payload else "{}"
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO ingestion_events (id, idempotency_key, order_id, event_type, event_version, payload, status, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, NOW());
                """,
                row_id,
                idempotency_key,
                order_id,
                event_type,
                event_version,
                payload_json,
                status,
            )
            return True
        except UniqueViolationError:
            return False


async def get_latest_event_type(pool: asyncpg.Pool, order_id: str) -> str | None:
    """Return the event_type of the most recent event for this order_id, or None if no events."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT event_type FROM ingestion_events
            WHERE order_id = $1
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            order_id,
        )
        return row["event_type"] if row else None
