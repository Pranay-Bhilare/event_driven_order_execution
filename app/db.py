"""
Async Postgres: ingestion_events (event log) + orders (current state per order).
Worker processes each event in a single transaction: insert event first, then lock order row, validate, update state.
"""
import json
import uuid
import asyncpg
from asyncpg.exceptions import UniqueViolationError

from app.config import settings
from app.order_state import is_valid_transition

_pool: asyncpg.Pool | None = None


class DuplicateEventError(Exception):
    """Raised when event_id already exists (UniqueViolation). Transaction will roll back."""


class InvalidTransitionError(Exception):
    """Raised when order state transition is not allowed. Transaction will roll back."""
    def __init__(self, current_state: str | None = None):
        self.current_state = current_state
        super().__init__(current_state)


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
        await conn.execute("DROP TABLE IF EXISTS orders;")
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
        await conn.execute("""
            CREATE TABLE orders (
                order_id VARCHAR(255) PRIMARY KEY,
                current_state VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)


async def process_event_transaction(
    pool: asyncpg.Pool,
    event_id: str,
    order_id: str,
    event_type: str,
    event_version: int,
    payload: dict,
) -> str:
    """
    Process one event in a single transaction.
    - Insert into ingestion_events first (UNIQUE on event_id = idempotency).
    - SELECT order FOR UPDATE; create order if missing (only for ORDER_CREATED); else validate transition and update.
    Returns: "inserted" | "duplicate" | "invalid_transition"
    On duplicate or invalid_transition, raises so transaction rolls back; caller catches and returns the result.
    """
    payload_json = json.dumps(payload) if payload else "{}"
    row_id = uuid.uuid4()
    idempotency_key = event_id
    status = "COMPLETED"

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
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
                except UniqueViolationError:
                    raise DuplicateEventError()

                row = await conn.fetchrow(
                    "SELECT current_state FROM orders WHERE order_id = $1 FOR UPDATE;",
                    order_id,
                )

                if row is None:
                    if event_type != "ORDER_CREATED":
                        raise InvalidTransitionError(current_state=None)
                    await conn.execute(
                        """
                        INSERT INTO orders (order_id, current_state, updated_at)
                        VALUES ($1, $2, NOW());
                        """,
                        order_id,
                        "ORDER_CREATED",
                    )
                else:
                    current_state = row["current_state"]
                    if not is_valid_transition(current_state, event_type):
                        raise InvalidTransitionError(current_state=current_state)
                    await conn.execute(
                        """
                        UPDATE orders SET current_state = $1, updated_at = NOW() WHERE order_id = $2;
                        """,
                        event_type,
                        order_id,
                    )
        except DuplicateEventError:
            return "duplicate"
        except InvalidTransitionError:
            raise

    return "inserted"
