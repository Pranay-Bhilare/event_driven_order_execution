from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ingestion"
    worker_concurrency: int = 10  # max concurrent message processing (semaphore limit)
    worker_max_retries: int = 5  # after this many attempts, move to DLQ (attempts 0..4 = 5 tries)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
