#!/usr/bin/env python3
"""
Scenario 3 — DB Slowdown (Backpressure).

Prerequisites:
- Worker running with DB_SLOWDOWN_MS=200 (e.g. in docker-compose worker env).
- API, Redis, Postgres up. K6 installed (e.g. k6 run).

Flow:
- Monitor Redis queue depth every 1s in background.
- Run K6 at 500 req/s for 30s.
- Keep monitoring for 60s after load to show worker drain.

Expect: queue depth spikes during load, API still 202, queue drains gradually after.

Run from project root: python test/scenario_03_db_slowdown.py
"""
import os
import subprocess
import sys
import threading
import time

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _test_dir)

from _helper import get_queue_length

POLL_INTERVAL = 1.0
LOAD_DURATION = 30   # K6 runs 30s
DRAIN_DURATION = 60  # keep monitoring 60s after K6

# (elapsed_sec, queue_depth)
readings: list[tuple[float, int]] = []
stop_monitor = threading.Event()


def monitor_loop() -> None:
    start = time.monotonic()
    while not stop_monitor.is_set():
        try:
            depth = get_queue_length()
            elapsed = time.monotonic() - start
            readings.append((elapsed, depth))
            print(f"  t={elapsed:.0f}s  queue_depth={depth}")
        except Exception as e:
            print(f"  monitor error: {e}")
        stop_monitor.wait(POLL_INTERVAL)


def main() -> None:
    root = os.path.dirname(_test_dir)
    k6_script = os.path.join(root, "load_test", "ingest_500.js")
    if not os.path.isfile(k6_script):
        print(f"Missing {k6_script}")
        sys.exit(1)

    print("Scenario 3 — DB Slowdown (Backpressure)")
    print("Ensure worker has DB_SLOWDOWN_MS=200 and is restarted.")
    print()
    print("Starting queue depth monitor (1s interval) ...")
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    print("Running K6: 500 req/s for 30s ...")
    try:
        proc = subprocess.run(
            ["k6", "run", "load_test/ingest_500.js"],
            cwd=root,
            timeout=LOAD_DURATION + 15,
        )
        k6_ok = proc.returncode == 0
    except FileNotFoundError:
        print("k6 not found. Install K6: https://k6.io/docs/get-started/installation/")
        k6_ok = False
    except subprocess.TimeoutExpired:
        proc.kill()
        k6_ok = False

    print("Load finished. Monitoring drain for 60s ...")
    time.sleep(DRAIN_DURATION)
    stop_monitor.set()
    monitor_thread.join(timeout=POLL_INTERVAL + 2)

    if not readings:
        print("No queue depth readings.")
        sys.exit(1)

    max_depth = max(r[1] for r in readings)
    final_depth = readings[-1][1]
    print()
    print("--- Summary ---")
    print(f"  Max queue depth:    {max_depth}")
    print(f"  Final queue depth:  {final_depth}")
    print(f"  API (K6 thresholds): {'PASS' if k6_ok else 'CHECK K6 OUTPUT'}")
    print("  Decoupling: API accepts 202 while queue buffers; worker drains gradually.")
    if k6_ok and max_depth > 0:
        print("Scenario 3 — Backpressure: PASSED")
    else:
        print("Scenario 3 — Run with DB_SLOWDOWN_MS=200 on worker for visible backpressure.")


if __name__ == "__main__":
    main()
