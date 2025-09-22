from datetime import datetime

from pydantic import BaseModel


class RedisConnectorIndexPayload(BaseModel):
    index_attempt_id: int | None
    started: datetime | None
    submitted: datetime
    celery_task_id: str | None
