from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response

from app.metrics import get_metrics_bytes, get_metrics_content_type, sqs_queue_messages_in_flight, sqs_queue_messages_waiting
from app.redis_client import close_redis, get_redis
from app.routes import admin, events
from app.sqs_client import get_queue_depth


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_redis()
    yield
    await close_redis()


app = FastAPI(title="Ingestion Engine", lifespan=lifespan)
app.include_router(events.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint: events_ingested_total, SQS queue depth (when using SQS)."""
    try:
        from app.config import settings
        if settings.sqs_queue_url:
            waiting, in_flight = await get_queue_depth()
            sqs_queue_messages_waiting.set(waiting)
            sqs_queue_messages_in_flight.set(in_flight)
    except Exception:
        pass
    return Response(
        content=get_metrics_bytes(),
        media_type=get_metrics_content_type(),
    )
