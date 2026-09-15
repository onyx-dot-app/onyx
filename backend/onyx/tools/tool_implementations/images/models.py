from pydantic import BaseModel

from onyx.tools.progress import GeneratedImage


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class FinalImageGenerationResponse(BaseModel):
    generated_images: list[GeneratedImage]
