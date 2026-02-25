from pydantic import BaseModel


class CodeInterpreterServerUpdate(BaseModel):
    enabled: bool


class CodeInterpreterServerHealth(BaseModel):
    healthy: bool
