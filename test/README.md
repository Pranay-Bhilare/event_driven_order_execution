# Scenario tests — Order lifecycle

Simple scripts to verify behaviour end-to-end (API → queue → worker → DB).

**Prerequisites:** API and worker running (e.g. `docker compose up`), Redis and Postgres.

**Run from project root:**

```bash
python test/scenario_01_normal_flow.py
```

Optional env (defaults work for local docker):

- `API_URL` — default `http://localhost:8000`
- `DATABASE_URL` — default `postgresql://postgres:postgres@localhost:5432/ingestion`
- `REDIS_URL` — default `redis://localhost:6379/0`

## Scenarios

| Script | Description |
|--------|-------------|
| `scenario_01_normal_flow.py` | Valid sequence CREATED → PAYMENT → SHIPPED → DELIVERED. All persisted, no DLQ. |

Add new scripts (e.g. `scenario_02_invalid_transition.py`) as needed; use `test/_helper.py` for ingest, DB fetch, and DLQ length.
