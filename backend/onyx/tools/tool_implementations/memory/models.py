from pydantic import BaseModel


class MemoryToolResponse(BaseModel):
    memory_text: str
    index_to_replace: int | None  # None = add new, int = replace at 0-based index
