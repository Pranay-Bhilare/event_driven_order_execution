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
