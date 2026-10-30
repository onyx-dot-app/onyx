from typing import Literal

from pydantic import BaseModel

from onyx.image_gen.interfaces import ImageShape
from onyx.tools.models import GeneratedImage


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class FinalImageGenerationResponse(BaseModel):
    type: Literal["image_generation_result"] = "image_generation_result"
    generated_images: list[GeneratedImage]


class ImageGenerationArguments(BaseModel):
    prompt: str
    shape: ImageShape = ImageShape.SQUARE
