from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.redis_client import close_redis, get_redis
from app.routes import events


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_redis()
    yield
    await close_redis()


app = FastAPI(title="Ingestion Engine", lifespan=lifespan)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
