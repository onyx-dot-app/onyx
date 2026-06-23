from pydantic import BaseModel
from pydantic import Field


class ForgeError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, object] = Field(default_factory=dict)
    occurred_at: str
