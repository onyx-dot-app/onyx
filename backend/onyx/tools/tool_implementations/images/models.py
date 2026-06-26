from pydantic import BaseModel

from onyx.image_gen.interfaces import ImageShape
from onyx.server.query_and_chat.streaming_models import GeneratedImage

__all__ = [
    "ImageGenerationResponse",
    "ImageShape",
    "FinalImageGenerationResponse",
]


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class FinalImageGenerationResponse(BaseModel):
    generated_images: list[GeneratedImage]
