/**
 * Single scenario: 500 req/s (125 orders/s × 4 events) for 30s.
 * Each iteration = one order = valid sequence CREATED → PAYMENT → SHIPPED → DELIVERED.
 * Use for Scenario 3 — DB Slowdown (backpressure) tests.
 * Run: k6 run load_test/ingest_500.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.API_URL || 'http://localhost:8000';
const EVENT_TYPES = ['ORDER_CREATED', 'PAYMENT_CONFIRMED', 'ORDER_SHIPPED', 'ORDER_DELIVERED'];

export const options = {
  scenarios: {
    burst_500: {
      executor: 'constant-arrival-rate',
      rate: 125,
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 100,
      maxVUs: 1000,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<5000'],
  },
};

export default function () {
  const orderId = `ord-${__VU}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  for (let i = 0; i < EVENT_TYPES.length; i++) {
    const eventType = EVENT_TYPES[i];
    const payload = JSON.stringify({
      event_id: `evt-${__VU}-${Date.now()}-${i}-${Math.random().toString(36).slice(2)}`,
      order_id: orderId,
      event_type: eventType,
      event_version: 1,
      payload: {},
    });
    const res = http.post(`${BASE}/events/ingest`, payload, {
      headers: { 'Content-Type': 'application/json' },
    });
    check(res, { 'status 202 or 200': (r) => r.status === 202 || r.status === 200 });
    sleep(0.05);
  }
}
