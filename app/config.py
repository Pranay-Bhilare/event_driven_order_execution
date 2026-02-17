from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ingestion"
    worker_concurrency: int = 10  # max concurrent message processing (semaphore limit)
    worker_max_retries: int = 5  # after this many attempts, move to DLQ (attempts 0..4 = 5 tries)
    db_slowdown_ms: int = 400  # artificial delay per insert (e.g. 200 for backpressure tests)

    # AWS SQS (required for queue): main queue and DLQ
    aws_region: str = "ap-south-1"
    sqs_queue_url: str | None = None
    sqs_dlq_url: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
