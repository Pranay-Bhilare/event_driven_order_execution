"""
Worker: pull messages from Redis or AWS SQS, insert into Postgres.
- Redis: exponential backoff + manual DLQ. SQS: don't delete on failure; SQS redrive to DLQ after max receives.
- Prometheus /metrics on port 9090 (worker metrics).
- Graceful shutdown on SIGTERM.
Run: python -m app.worker
"""
import asyncio
import json
import logging
import signal
import sys
import threading
import time

import redis.asyncio as redis

from app.config import settings
from app.db import close_pool, get_pool, get_latest_event_type, init_schema, insert_event
from app.metrics import (
    events_rejected_invalid_transition_total,
    messages_dlq_total,
    messages_failed_total,
    messages_processed_total,
)
from app.order_state import is_valid_transition
from app.queue import INGESTION_DLQ_KEY, INGESTION_QUEUE_KEY
from app.sqs_client import change_message_visibility, delete_message, receive_messages, send_message_to_dlq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BRPOP_TIMEOUT = 5
GRACEFUL_SHUTDOWN_WAIT_SEC = 30
WORKER_METRICS_PORT = 9090


def _start_metrics_server() -> None:
    from prometheus_client import start_http_server
    start_http_server(WORKER_METRICS_PORT)


async def process_one_redis(
    r: redis.Redis,
    pool,
    raw: str,
    sem: asyncio.Semaphore,
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON from queue: %s", e)
        return
    event_id = data.get("event_id")
    order_id = data.get("order_id")
    event_type = data.get("event_type")
    event_version = data.get("event_version", 1)
    payload = data.get("payload") or {}
    attempts = data.get("attempts", 0)
    if not event_id:
        logger.warning("Message missing event_id, skipping")
        return
    if not order_id or not event_type:
        logger.warning("Message missing order_id or event_type, skipping")
        return

    async with sem:
        current_state = await get_latest_event_type(pool, order_id)
        if not is_valid_transition(current_state, event_type):
            events_rejected_invalid_transition_total.labels(
                current_state=current_state or "none",
                attempted_event_type=event_type,
            ).inc()
            dlq_message = json.dumps({
                "event_id": event_id,
                "order_id": order_id,
                "event_type": event_type,
                "event_version": event_version,
                "payload": payload,
                "attempts": attempts,
                "reason": "invalid_transition",
                "current_state": current_state,
                "attempted_event_type": event_type,
                "rejected_at": time.time(),
            })
            await r.lpush(INGESTION_DLQ_KEY, dlq_message)
            messages_dlq_total.inc()
            logger.warning(
                "Rejected invalid transition order_id=%s current=%s attempted=%s -> DLQ",
                order_id, current_state, event_type,
            )
            return
        try:
            inserted = await insert_event(pool, event_id, order_id, event_type, event_version, payload)
            if inserted:
                logger.info("Processed event_id=%s order_id=%s %s", event_id, order_id, event_type)
                messages_processed_total.inc()
            else:
                logger.info("Duplicate event_id=%s (UNIQUE constraint), skipped", event_id)
                messages_processed_total.inc()
        except Exception as e:
            messages_failed_total.inc()
            logger.exception("Failed to process event_id=%s (attempt %d): %s", event_id, attempts + 1, e)
            next_attempts = attempts + 1
            if next_attempts >= settings.worker_max_retries:
                dlq_message = json.dumps({
                    "event_id": event_id,
                    "order_id": order_id,
                    "event_type": event_type,
                    "event_version": event_version,
                    "payload": payload,
                    "attempts": next_attempts,
                    "last_error": str(e),
                    "failed_at": time.time(),
                })
                await r.lpush(INGESTION_DLQ_KEY, dlq_message)
                messages_dlq_total.inc()
                logger.warning("Moved event_id=%s to DLQ after %d attempts", event_id, settings.worker_max_retries)
            else:
                backoff_sec = 2 ** attempts
                logger.info("Re-queuing event_id=%s in %ds (attempt %d/%d)", event_id, backoff_sec, next_attempts, settings.worker_max_retries)
                await asyncio.sleep(backoff_sec)
                retry_message = json.dumps({
                    "event_id": event_id,
                    "order_id": order_id,
                    "event_type": event_type,
                    "event_version": event_version,
                    "payload": payload,
                    "attempts": next_attempts,
                })
                await r.lpush(INGESTION_QUEUE_KEY, retry_message)


async def process_one_sqs(
    pool,
    body: str,
    receipt_handle: str,
    receive_count: int,
    sem: asyncio.Semaphore,
) -> None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON from SQS")
        return
    event_id = data.get("event_id")
    order_id = data.get("order_id")
    event_type = data.get("event_type")
    event_version = data.get("event_version", 1)
    payload = data.get("payload") or {}
    if not event_id:
        logger.warning("Message missing event_id, skipping")
        return
    if not order_id or not event_type:
        logger.warning("Message missing order_id or event_type, skipping")
        return

    async with sem:
        current_state = await get_latest_event_type(pool, order_id)
        if not is_valid_transition(current_state, event_type):
            events_rejected_invalid_transition_total.labels(
                current_state=current_state or "none",
                attempted_event_type=event_type,
            ).inc()
            dlq_body = {
                "event_id": event_id,
                "order_id": order_id,
                "event_type": event_type,
                "event_version": event_version,
                "payload": payload,
                "reason": "invalid_transition",
                "current_state": current_state,
                "attempted_event_type": event_type,
                "rejected_at": time.time(),
            }
            await send_message_to_dlq(dlq_body)
            await asyncio.to_thread(delete_message, receipt_handle)
            logger.warning(
                "Rejected invalid transition order_id=%s current=%s attempted=%s (deleted from queue)",
                order_id, current_state, event_type,
            )
            return
        try:
            inserted = await insert_event(pool, event_id, order_id, event_type, event_version, payload)
            if inserted:
                logger.info("Processed event_id=%s order_id=%s %s", event_id, order_id, event_type)
                messages_processed_total.inc()
                await asyncio.to_thread(delete_message, receipt_handle)
            else:
                logger.info("Duplicate event_id=%s (UNIQUE constraint), skipped", event_id)
                messages_processed_total.inc()
                await asyncio.to_thread(delete_message, receipt_handle)
        except Exception as e:
            messages_failed_total.inc()
            logger.exception("Failed to process event_id=%s (receive #%d): %s", event_id, receive_count, e)
            # Don't delete: message will reappear after visibility timeout; after max receives SQS moves to DLQ
            backoff = min(2 ** receive_count, 900)
            await asyncio.to_thread(change_message_visibility, receipt_handle, backoff)


async def run_worker_redis(shutdown_event: asyncio.Event) -> None:
    pool = await get_pool()
    await init_schema(pool)
    sem = asyncio.Semaphore(settings.worker_concurrency)
    logger.info(
        "Schema ready. Backend=Redis. Listening on %s (concurrency=%d, max_retries=%d) ...",
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
            t = asyncio.create_task(process_one_redis(r, pool, raw, sem))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
    finally:
        if tasks:
            logger.info("Graceful shutdown: waiting for %d in-flight task(s) (max %ds) ...", len(tasks), GRACEFUL_SHUTDOWN_WAIT_SEC)
            _, pending = await asyncio.wait(tasks, timeout=GRACEFUL_SHUTDOWN_WAIT_SEC, return_when=asyncio.ALL_COMPLETED)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await r.aclose()
        await close_pool()
        logger.info("Worker stopped.")


async def run_worker_sqs(shutdown_event: asyncio.Event) -> None:
    pool = await get_pool()
    await init_schema(pool)
    sem = asyncio.Semaphore(settings.worker_concurrency)
    logger.info(
        "Schema ready. Backend=SQS. Queue=%s (concurrency=%d) ...",
        settings.sqs_queue_url,
        settings.worker_concurrency,
    )
    tasks: set[asyncio.Task] = set()
    try:
        while not shutdown_event.is_set():
            messages = await asyncio.to_thread(receive_messages, 10, 5)
            for msg in messages:
                body = msg.get("Body") or "{}"
                receipt = msg.get("ReceiptHandle") or ""
                attrs = msg.get("Attributes") or {}
                receive_count = int(attrs.get("ApproximateReceiveCount", 1))
                t = asyncio.create_task(process_one_sqs(pool, body, receipt, receive_count, sem))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
    finally:
        if tasks:
            logger.info("Graceful shutdown: waiting for %d in-flight task(s) (max %ds) ...", len(tasks), GRACEFUL_SHUTDOWN_WAIT_SEC)
            _, pending = await asyncio.wait(tasks, timeout=GRACEFUL_SHUTDOWN_WAIT_SEC, return_when=asyncio.ALL_COMPLETED)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await close_pool()
        logger.info("Worker stopped.")


async def run_worker(shutdown_event: asyncio.Event) -> None:
    if settings.sqs_queue_url:
        await run_worker_sqs(shutdown_event)
    else:
        await run_worker_redis(shutdown_event)


def main() -> None:
    threading.Thread(target=_start_metrics_server, daemon=True).start()
    logger.info("Metrics server listening on port %s", WORKER_METRICS_PORT)

    shutdown_event = asyncio.Event()

    def on_signal():
        shutdown_event.set()

    loop = asyncio.new_event_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, on_signal)
    except NotImplementedError:
        signal.signal(signal.SIGTERM, lambda *a: shutdown_event.set())
        signal.signal(signal.SIGINT, lambda *a: shutdown_event.set())

    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_worker(shutdown_event))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
