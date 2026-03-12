## Event-Driven Order Execution Pipeline

FastAPI-based service that accepts order lifecycle events over HTTP, pushes them into a queue, and processes them asynchronously with a worker. The worker applies transactional state transitions in PostgreSQL and exposes metrics for monitoring through Prometheus and Grafana.

### Architecture overview

- **API service (`api`)**
  - FastAPI app exposing `/events/ingest`.
  - Validates the incoming event and runs an idempotency check in `Redis` so the same `event_id` is not processed twice.
  - Pushes the validated event into a queue (backed by SQS in the code) so HTTP request handling is decoupled from database writes.

- **Worker service (`worker`)**
  - Long‑running process that pulls messages from the queue.
  - For each message, runs a single database transaction:
    - Inserts the event row.
    - Locks the corresponding order row with row‑level locking.
    - Validates the state transition and updates the current state.
  - On invalid transitions or repeated failures, sends the message to a separate dead‑letter queue and keeps normal traffic flowing.

- **PostgreSQL (`postgres`)**
  - Stores orders, events, and state transition history.
  - Row‑level locking is used so concurrent events on the same order are serialized cleanly.

- **Redis (`redis`)**
  - Used as a simple idempotency store keyed by `event_id`.
  - Prevents duplicates from being re‑enqueued or re‑processed.

- **Prometheus + Grafana**
  - `worker` and `api` expose Prometheus metrics (HTTP status codes, events processed, failures, queue depth, etc.).
  - Prometheus scrapes metrics, and Grafana shows dashboards for:
    - Events per second
    - Processing failures / DLQ sends
    - Worker throughput and lag

### Running the system

Prerequisites:

- Docker and Docker Compose installed

Steps:

1. **Clone the repository**

   ```bash
   git clone <repo-url>
   cd backend-project
   ```

2. **Create a `.env` file**

   At the project root, create `.env` with at least:

   ```env
   SQS_QUEUE_URL=<your-queue-url>
   SQS_DLQ_URL=<optional-dlq-url>
   AWS_REGION=<region>
   ```

   Plus any other environment variables you already use in the app (for example DB/Redis URLs, worker concurrency, etc.).

3. **Start everything**

   ```bash
   docker compose up --build
   ```

   This will start:

   - API on `http://localhost:8000`
   - Worker metrics on `http://localhost:9090/metrics`
   - Prometheus on `http://localhost:9091`
   - Grafana on `http://localhost:3000`
   - Redis on `localhost:6379`
   - Postgres on `localhost:5432`

### Hitting the API

Example request to ingest an event:

```bash
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "ev-123",
    "order_id": "order-1",
    "event_type": "ORDER_CREATED",
    "event_version": 1,
    "payload": { "amount": 1000 }
  }'
```

If the `event_id` is new, the API returns `202 Accepted` and the worker will pick it up from the queue. If the same `event_id` is sent again, the API returns `200` and the event is treated as already processed.

### Observability

- **Prometheus**
  - UI: `http://localhost:9091`
  - Scrapes:
    - API metrics from the FastAPI process
    - Worker metrics from the worker process

- **Grafana**
  - UI: `http://localhost:3000`
  - Default credentials: `admin` / `admin` (as configured in `docker-compose.yml`)
  - Comes pre‑configured to use Prometheus as a data source.
  - Dashboards show:
    - Total ingested events by type
    - Number of successfully processed events
    - Number of failed/invalid events and DLQ volume
    - Queue depth and processing latency

### Failure scenarios and DLQ

The worker is written to handle a few realistic failure modes:

- **Worker crash or restart**
  - Unacked messages remain in the queue and will be redelivered after visibility timeout expires.

- **Database slowdowns**
  - Worker concurrency is bounded; slowdown increases processing lag but does not take down the API.

- **Duplicate deliveries**
  - Redis idempotency key on the API side and unique constraints on the database side ensure that re‑delivered events don’t corrupt state.

- **Unrecoverable events**
  - Invalid transitions or repeatedly failing events are pushed to a dedicated dead‑letter queue for later inspection and replay.

### Load testing

You can generate load against the `/events/ingest` endpoint with any HTTP load‑test tool (k6, Locust, wrk, etc.):

- Drive a burst of `POST /events/ingest` requests with different `event_id`/`order_id`.
- Watch Grafana to see:
  - How queue depth and processing lag react.
  - How many events end up in DLQ when you inject bad transitions.

