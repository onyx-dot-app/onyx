from pydantic import BaseModel


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str


# Needed for PydanticType
class GeneratedImageFullResult(BaseModel):
    images: list[GeneratedImage]
