"""
Prometheus metrics: events ingested (API), messages processed/failed (worker), queue depth (SQS).
"""
from prometheus_client import Counter, Gauge, generate_latest

# API: events accepted for ingestion (by order lifecycle event type)
events_ingested_total = Counter(
    "events_ingested_total",
    "Total order lifecycle events accepted (202) for ingestion",
    ["event_type"],
)

# Worker: processing outcomes
messages_processed_total = Counter(
    "messages_processed_total",
    "Total messages successfully processed",
)
messages_failed_total = Counter(
    "messages_failed_total",
    "Total messages that failed processing (retried or sent to DLQ)",
)
messages_dlq_total = Counter(
    "messages_dlq_total",
    "Total messages moved to DLQ after max retries",
)
events_rejected_invalid_transition_total = Counter(
    "events_rejected_invalid_transition_total",
    "Total events rejected due to invalid order lifecycle transition",
    ["current_state", "attempted_event_type"],
)

# SQS queue depth (when using SQS) - backpressure / consumer lag
sqs_queue_messages_waiting = Gauge(
    "sqs_queue_messages_waiting",
    "Approximate number of messages waiting in SQS (main queue)",
)
sqs_queue_messages_in_flight = Gauge(
    "sqs_queue_messages_in_flight",
    "Approximate number of messages in flight (received but not yet deleted)",
)


def get_metrics_content_type():
    return "text/plain; charset=utf-8; version=0.0.4"


def get_metrics_bytes():
    return generate_latest()
