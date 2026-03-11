from pydantic import BaseModel


class CodeInterpreterServer(BaseModel):
    enabled: bool


class CodeInterpreterServerHealth(BaseModel):
    healthy: bool
