#!/usr/bin/env python3
"""
Scenario 1 — Normal flow.

Send valid sequence: ORDER_CREATED → PAYMENT_CONFIRMED → ORDER_SHIPPED → ORDER_DELIVERED.

Expect:
- All 4 events return 202 (accepted)
- After worker processes: 4 rows persisted for order_id, in correct order
- No messages in DLQ

Run: python test/scenario_01_normal_flow.py
Requires: API and worker running (e.g. docker compose up), Redis, Postgres.
"""
import asyncio
import os
import sys
import time
import uuid

# test/ directory on path so _helper is found (avoid "test" package - shadows stdlib)
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _test_dir)

from _helper import (
    fetch_events_for_order,
    get_dlq_length,
    ingest_event,
)

EXPECTED_SEQUENCE = [
    "ORDER_CREATED",
    "PAYMENT_CONFIRMED",
    "ORDER_SHIPPED",
    "ORDER_DELIVERED",
]


def main() -> None:
    order_id = f"ord-test-normal-{uuid.uuid4().hex[:12]}"
    events = [
        ("ORDER_CREATED", f"evt-created-{uuid.uuid4().hex[:8]}"),
        ("PAYMENT_CONFIRMED", f"evt-payment-{uuid.uuid4().hex[:8]}"),
        ("ORDER_SHIPPED", f"evt-shipped-{uuid.uuid4().hex[:8]}"),
        ("ORDER_DELIVERED", f"evt-delivered-{uuid.uuid4().hex[:8]}"),
    ]

    print(f"Order ID: {order_id}")
    print("Sending valid sequence: CREATED → PAYMENT → SHIPPED → DELIVERED")

    dlq_before = get_dlq_length()
    for event_type, event_id in events:
        status, body = ingest_event(event_id=event_id, order_id=order_id, event_type=event_type)
        if status not in (200, 202):
            print(f"  FAIL {event_type}: status={status} body={body}")
            sys.exit(1)
        print(f"  {event_type}: {status}")

    # Give worker time to process
    print("Waiting 3s for worker to process ...")
    time.sleep(5)

    persisted = asyncio.run(fetch_events_for_order(order_id))
    dlq_after = get_dlq_length()

    # Assert
    ok = True
    if persisted != EXPECTED_SEQUENCE:
        print(f"  FAIL: Expected persisted {EXPECTED_SEQUENCE}, got {persisted}")
        ok = False
    else:
        print("  All persisted:", persisted)

    if dlq_after != dlq_before:
        print(f"  FAIL: DLQ length changed from {dlq_before} to {dlq_after} (expected no new DLQ messages)")
        ok = False
    else:
        print(f"  No DLQ (length still {dlq_after})")

    if ok:
        print("Scenario 1 — Normal flow: PASSED")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
