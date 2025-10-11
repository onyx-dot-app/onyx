from typing import ClassVar

from pydantic import BaseModel


class QdrantConfig(BaseModel):
    url: ClassVar[str] = "http://localhost:6333"
