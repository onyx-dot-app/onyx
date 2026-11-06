from typing import Literal

from pydantic import BaseModel, model_validator

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

    @model_validator(mode="before")
    @classmethod
    def null_uses_default_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {
            key: item
            for key, item in value.items()
            if key != "shape" or item is not None
        }
