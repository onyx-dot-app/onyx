from pydantic import BaseModel


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


# Needed for PydanticType
class GeneratedImageFullResult(BaseModel):
    images: list[GeneratedImage]
