"""
AWS SQS helpers: send and receive messages. Used when SQS_QUEUE_URL is set.
"""
import asyncio
import json
from typing import Any

import boto3

from app.config import settings

_sqs_client: Any = None


def _get_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs_client


async def send_message(body: dict) -> None:
    """Send message to main queue (run boto3 in thread to not block)."""
    client = _get_client()
    await asyncio.to_thread(
        client.send_message,
        QueueUrl=settings.sqs_queue_url,
        MessageBody=json.dumps(body),
    )


async def send_message_to_dlq(body: dict) -> None:
    """Send message to DLQ when configured. No-op if sqs_dlq_url is not set."""
    if not settings.sqs_dlq_url:
        return
    client = _get_client()
    await asyncio.to_thread(
        client.send_message,
        QueueUrl=settings.sqs_dlq_url,
        MessageBody=json.dumps(body),
    )


def receive_messages(max_number: int = 10, wait_seconds: int = 5) -> list[dict]:
    """Sync receive (used by worker in thread). Returns list of {ReceiptHandle, Body}."""
    client = _get_client()
    resp = client.receive_message(
        QueueUrl=settings.sqs_queue_url,
        MaxNumberOfMessages=max_number,
        WaitTimeSeconds=wait_seconds,
        MessageAttributeNames=["All"],
        AttributeNames=["ApproximateReceiveCount"],
    )
    return resp.get("Messages") or []


def delete_message(receipt_handle: str) -> None:
    """Sync delete after successful process."""
    client = _get_client()
    client.delete_message(
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=receipt_handle,
    )


def change_message_visibility(receipt_handle: str, visibility_timeout: int) -> None:
    """Optional: delay next visibility for backoff."""
    client = _get_client()
    client.change_message_visibility(
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=visibility_timeout,
    )


async def get_queue_depth() -> tuple[int, int]:
    """Return (ApproximateNumberOfMessages, ApproximateNumberOfMessagesNotVisible) for metrics."""
    if not settings.sqs_queue_url:
        return 0, 0
    client = _get_client()

    def _get():
        r = client.get_queue_attributes(
            QueueUrl=settings.sqs_queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )
        attrs = r.get("Attributes") or {}
        return (
            int(attrs.get("ApproximateNumberOfMessages", 0)),
            int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        )

    return await asyncio.to_thread(_get)


def receive_messages_from_dlq(max_number: int = 10, wait_seconds: int = 0) -> list[dict]:
    """Receive messages from DLQ. Returns list of {ReceiptHandle, Body}."""
    if not settings.sqs_dlq_url:
        return []
    client = _get_client()
    resp = client.receive_message(
        QueueUrl=settings.sqs_dlq_url,
        MaxNumberOfMessages=max_number,
        WaitTimeSeconds=wait_seconds,
    )
    return resp.get("Messages") or []


def delete_message_from_dlq(receipt_handle: str) -> None:
    """Delete message from DLQ after processing."""
    if not settings.sqs_dlq_url:
        return
    client = _get_client()
    client.delete_message(
        QueueUrl=settings.sqs_dlq_url,
        ReceiptHandle=receipt_handle,
    )


async def replay_dlq_to_main(limit: int = 100) -> int:
    """
    Read messages from DLQ, re-send event payload to main queue, delete from DLQ.
    Returns number of messages replayed.
    """
    if not settings.sqs_dlq_url or not settings.sqs_queue_url:
        return 0
    replayed = 0
    while replayed < limit:
        messages = await asyncio.to_thread(receive_messages_from_dlq, 10, 0)
        if not messages:
            break
        for msg in messages:
            if replayed >= limit:
                break
            body_str = msg.get("Body") or "{}"
            receipt = msg.get("ReceiptHandle") or ""
            try:
                data = json.loads(body_str)
            except json.JSONDecodeError:
                await asyncio.to_thread(delete_message_from_dlq, receipt)
                replayed += 1
                continue
            event_id = data.get("event_id")
            order_id = data.get("order_id")
            event_type = data.get("event_type")
            event_version = data.get("event_version", 1)
            payload = data.get("payload") or {}
            if not event_id or not order_id or not event_type:
                await asyncio.to_thread(delete_message_from_dlq, receipt)
                replayed += 1
                continue
            main_body = {
                "event_id": event_id,
                "order_id": order_id,
                "event_type": event_type,
                "event_version": event_version,
                "payload": payload,
                "attempts": 0,
            }
            await send_message(main_body)
            await asyncio.to_thread(delete_message_from_dlq, receipt)
            replayed += 1
    return replayed
