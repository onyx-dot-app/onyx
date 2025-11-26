from enum import Enum

from pydantic import BaseModel

from onyx.server.query_and_chat.streaming_models import GeneratedImage


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class ImageShape(str, Enum):
    SQUARE = "square"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class FinalImageGenerationResponse(BaseModel):
    generated_images: list[GeneratedImage]
