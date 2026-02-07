"""
Worker: pull messages from Redis queue (BRPOP), insert into Postgres.
Async: asyncio + redis.asyncio + asyncpg. Concurrency capped by Semaphore.
Run: python -m app.worker
"""
import asyncio
import json
import logging
import sys

import redis.asyncio as redis

from app.config import settings
from app.db import close_pool, get_pool, init_schema, insert_event
from app.queue import INGESTION_QUEUE_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BRPOP_TIMEOUT = 5


async def process_one(
    r: redis.Redis,
    pool,
    raw: str,
    sem: asyncio.Semaphore,
) -> None:
    """Process a single message; semaphore limits concurrent DB work."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON from queue: %s", e)
        return
    event_id = data.get("event_id")
    source = data.get("source", "order_updates")
    payload = data.get("payload") or {}
    if not event_id:
        logger.warning("Message missing event_id, skipping")
        return

    async with sem:
        try:
            inserted = await insert_event(pool, event_id, source, payload)
            if inserted:
                logger.info("Processed event_id=%s", event_id)
            else:
                logger.info("Duplicate event_id=%s (UNIQUE constraint), skipped", event_id)
        except Exception as e:
            logger.exception("Failed to process event_id=%s: %s", event_id, e)
            await r.lpush(INGESTION_QUEUE_KEY, raw)
            logger.info("Re-queued event_id=%s for retry", event_id)


async def run_worker() -> None:
    pool = await get_pool()
    await init_schema(pool)
    sem = asyncio.Semaphore(settings.worker_concurrency)
    logger.info(
        "Schema ready. Listening on %s (concurrency=%d) ...",
        INGESTION_QUEUE_KEY,
        settings.worker_concurrency,
    )

    r = redis.from_url(settings.redis_url, decode_responses=True)
    tasks: set[asyncio.Task] = set()
    try:
        while True:
            result = await r.brpop(INGESTION_QUEUE_KEY, timeout=BRPOP_TIMEOUT)
            if result is None:
                continue
            _key, raw = result
            t = asyncio.create_task(process_one(r, pool, raw, sem))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
    finally:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await r.aclose()
        await close_pool()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
