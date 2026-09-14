from pydantic import BaseModel


class CodingAgentCallResult(BaseModel):
    answer: str
