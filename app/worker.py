"""
Worker: pull messages from SQS, process each event in a single DB transaction.
- Insert event first, then lock order row (FOR UPDATE), validate transition, update orders.current_state.
- SQS message deleted only after successful commit.
- Prometheus /metrics on port 9090. Graceful shutdown on SIGTERM.
Run: python -m app.worker
"""
import asyncio
import json
import logging
import signal
import sys
import threading
import time

from app.config import settings
from app.db import (
    DuplicateEventError,
    InvalidTransitionError,
    close_pool,
    get_pool,
    init_schema,
    process_event_transaction,
)
from app.metrics import (
    events_rejected_invalid_transition_total,
    messages_failed_total,
    messages_processed_total,
)
from app.sqs_client import change_message_visibility, delete_message, receive_messages, send_message_to_dlq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

GRACEFUL_SHUTDOWN_WAIT_SEC = 30
WORKER_METRICS_PORT = 9090


def _start_metrics_server() -> None:
    from prometheus_client import start_http_server
    start_http_server(WORKER_METRICS_PORT)


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
        if settings.db_slowdown_ms > 0:
            await asyncio.sleep(settings.db_slowdown_ms / 1000.0)
        try:
            result = await process_event_transaction(
                pool, event_id, order_id, event_type, event_version, payload
            )
        except InvalidTransitionError as e:
            events_rejected_invalid_transition_total.labels(
                current_state=e.current_state or "none",
                attempted_event_type=event_type,
            ).inc()
            dlq_body = {
                "event_id": event_id,
                "order_id": order_id,
                "event_type": event_type,
                "event_version": event_version,
                "payload": payload,
                "reason": "invalid_transition",
                "current_state": e.current_state,
                "rejected_at": time.time(),
            }
            await send_message_to_dlq(dlq_body)
            await asyncio.to_thread(delete_message, receipt_handle)
            return
        except DuplicateEventError:
            messages_processed_total.inc()
            await asyncio.to_thread(delete_message, receipt_handle)
            return
        except Exception as e:
            messages_failed_total.inc()
            logger.exception("Failed to process event_id=%s (receive #%d): %s", event_id, receive_count, e)
            backoff = min(2 ** receive_count, 900)
            await asyncio.to_thread(change_message_visibility, receipt_handle, backoff)
            return

        if result == "inserted":
            messages_processed_total.inc()
            await asyncio.to_thread(delete_message, receipt_handle)


async def run_worker(shutdown_event: asyncio.Event) -> None:
    if not settings.sqs_queue_url:
        raise RuntimeError("SQS_QUEUE_URL is required")
    pool = await get_pool()
    await init_schema(pool)
    sem = asyncio.Semaphore(settings.worker_concurrency)
    logger.info(
        "Schema ready. SQS queue=%s (concurrency=%d) ...",
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
            logger.info(
                "Graceful shutdown: waiting for %d in-flight task(s) (max %ds) ...",
                len(tasks), GRACEFUL_SHUTDOWN_WAIT_SEC,
            )
            _, pending = await asyncio.wait(tasks, timeout=GRACEFUL_SHUTDOWN_WAIT_SEC, return_when=asyncio.ALL_COMPLETED)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await close_pool()
        logger.info("Worker stopped.")


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
