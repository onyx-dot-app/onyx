from pydantic import BaseModel


class GroupCount(BaseModel):
    group: str
    count: int
