from enum import Enum

from pydantic import BaseModel


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class ImageShape(str, Enum):
    SQUARE = "square"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class FinalImageGenerationResponse(BaseModel):
    images: list[ImageGenerationResponse]
