from typing import Literal

from pydantic import BaseModel


class CodingAgentCallResult(BaseModel):
    type: Literal["coding_result"] = "coding_result"
    answer: str
