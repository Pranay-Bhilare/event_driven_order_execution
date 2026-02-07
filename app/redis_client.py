import redis.asyncio as redis
from app.config import settings

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def check_idempotency(key: str, ttl_seconds: int = 86400) -> bool:
    """
    Returns True if this key was already seen (duplicate) -> caller should return 200.
    Returns False if key is new -> caller should proceed and then set the key.
    Uses SETNX: set if not exists. If we set it, we're first; if not, duplicate.
    """
    r = await get_redis()
    was_set = await r.set(key, "1", nx=True, ex=ttl_seconds)
    return not was_set  # True = duplicate (already existed), False = new
