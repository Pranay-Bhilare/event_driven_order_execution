"""
Async Postgres access for the worker (asyncpg). Table has UNIQUE(idempotency_key)
so duplicate inserts raise UniqueViolationError — we catch and treat as already processed.
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_events (
                id UUID PRIMARY KEY,
                idempotency_key VARCHAR(255) NOT NULL,
                source VARCHAR(50),
                payload JSONB,
                status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
                attempts INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(idempotency_key)
            );
        """)


async def insert_event(pool: asyncpg.Pool, event_id: str, source: str, payload: dict) -> bool:
    """
    Insert one event. Returns True if inserted, False if duplicate (UniqueViolationError).
    Caller should ack the queue message in both cases (we don't re-queue duplicates).
    """
    row_id = uuid.uuid4()
    idempotency_key = event_id
    status = "COMPLETED"
    payload_json = json.dumps(payload) if payload else "{}"
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO ingestion_events (id, idempotency_key, source, payload, status, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, NOW());
                """,
                row_id,
                idempotency_key,
                source,
                payload_json,
                status,
            )
            return True
        except UniqueViolationError:
            return False
