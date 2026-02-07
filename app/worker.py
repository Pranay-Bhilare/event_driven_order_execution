"""
Worker: pull messages from Redis queue (BRPOP), insert into Postgres.
- Exponential backoff on failure; after max retries, move to DLQ.
- Graceful shutdown on SIGTERM (finish in-flight tasks then exit).
Run: python -m app.worker
"""
import asyncio
import json
import logging
import signal
import sys
import time

import redis.asyncio as redis

from app.config import settings
from app.db import close_pool, get_pool, init_schema, insert_event
from app.queue import INGESTION_DLQ_KEY, INGESTION_QUEUE_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BRPOP_TIMEOUT = 5
GRACEFUL_SHUTDOWN_WAIT_SEC = 30


async def process_one(
    r: redis.Redis,
    pool,
    raw: str,
    sem: asyncio.Semaphore,
) -> None:
    """
    Process a single message. On failure: exponential backoff then re-queue
    (with attempts+1); after max retries, push to DLQ.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON from queue: %s", e)
        return
    event_id = data.get("event_id")
    source = data.get("source", "order_updates")
    payload = data.get("payload") or {}
    attempts = data.get("attempts", 0)
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
            logger.exception("Failed to process event_id=%s (attempt %d): %s", event_id, attempts + 1, e)
            next_attempts = attempts + 1
            if next_attempts >= settings.worker_max_retries:
                dlq_message = json.dumps({
                    "event_id": event_id,
                    "source": source,
                    "payload": payload,
                    "attempts": next_attempts,
                    "last_error": str(e),
                    "failed_at": time.time(),
                })
                await r.lpush(INGESTION_DLQ_KEY, dlq_message)
                logger.warning("Moved event_id=%s to DLQ after %d attempts", event_id, settings.worker_max_retries)
            else:
                backoff_sec = 2 ** attempts
                logger.info("Re-queuing event_id=%s in %ds (attempt %d/%d)", event_id, backoff_sec, next_attempts, settings.worker_max_retries)
                await asyncio.sleep(backoff_sec)
                retry_message = json.dumps({
                    "event_id": event_id,
                    "source": source,
                    "payload": payload,
                    "attempts": next_attempts,
                })
                await r.lpush(INGESTION_QUEUE_KEY, retry_message)


async def run_worker(shutdown_event: asyncio.Event) -> None:
    pool = await get_pool()
    await init_schema(pool)
    sem = asyncio.Semaphore(settings.worker_concurrency)
    logger.info(
        "Schema ready. Listening on %s (concurrency=%d, max_retries=%d) ...",
        INGESTION_QUEUE_KEY,
        settings.worker_concurrency,
        settings.worker_max_retries,
    )

    r = redis.from_url(settings.redis_url, decode_responses=True)
    tasks: set[asyncio.Task] = set()
    try:
        while not shutdown_event.is_set():
            result = await r.brpop(INGESTION_QUEUE_KEY, timeout=BRPOP_TIMEOUT)
            if result is None:
                continue
            _key, raw = result
            t = asyncio.create_task(process_one(r, pool, raw, sem))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
    finally:
        if tasks:
            logger.info("Graceful shutdown: waiting for %d in-flight task(s) (max %ds) ...", len(tasks), GRACEFUL_SHUTDOWN_WAIT_SEC)
            done, pending = await asyncio.wait(tasks, timeout=GRACEFUL_SHUTDOWN_WAIT_SEC, return_when=asyncio.ALL_COMPLETED)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await r.aclose()
        await close_pool()
        logger.info("Worker stopped.")


def main() -> None:
    shutdown_event = asyncio.Event()

    def on_signal():
        shutdown_event.set()

    loop = asyncio.new_event_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, on_signal)
    except NotImplementedError:
        # Windows may not support add_signal_handler
        signal.signal(signal.SIGTERM, lambda *a: shutdown_event.set())
        signal.signal(signal.SIGINT, lambda *a: shutdown_event.set())

    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_worker(shutdown_event))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
