from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.sqs_client import replay_dlq_to_main

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/dlq/replay")
async def dlq_replay(limit: int = Query(default=100, ge=1, le=1000)) -> JSONResponse:
    """
    Replay messages from SQS DLQ to main queue.
    Each DLQ message is re-sent to the main queue and deleted from DLQ.
    Returns number of messages replayed.
    """
    replayed = await replay_dlq_to_main(limit=limit)
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "replayed": replayed},
    )
