from pydantic import BaseModel


class CodeInterpreterServer(BaseModel):
    enabled: bool


class CodeInterpreterServerHealth(BaseModel):
    connected: bool
    error: str = ""
