import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.API_URL || 'http://localhost:8000';

// Valid order lifecycle sequence (one order = 4 requests per iteration)
const EVENT_TYPES = ['ORDER_CREATED', 'PAYMENT_CONFIRMED', 'ORDER_SHIPPED', 'ORDER_DELIVERED'];

export const options = {
  scenarios: {
    // Scenario 1: 100 req/s = 25 orders/s for 1 min
    steady_100: {
      executor: 'constant-arrival-rate',
      rate: 25,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 10,
      maxVUs: 100,
      startTime: '0s',
    },
    // Scenario 2: 500 req/s = 125 orders/s (after 1 min)
    burst_500: {
      executor: 'constant-arrival-rate',
      rate: 125,
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 20,
      maxVUs: 200,
      startTime: '65s',
    },
    // Scenario 3: 1000 req/s = 250 orders/s
    spike_1000: {
      executor: 'constant-arrival-rate',
      rate: 250,
      timeUnit: '1s',
      duration: '15s',
      preAllocatedVUs: 200,
      maxVUs: 1000,
      startTime: '100s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
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
