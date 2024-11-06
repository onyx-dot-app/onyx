from datetime import datetime

from pydantic import BaseModel


class RedisConnectorDeletionFenceData(BaseModel):
    num_tasks: int | None
    submitted: datetime
