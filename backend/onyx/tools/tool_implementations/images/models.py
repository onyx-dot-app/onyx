from pydantic import BaseModel

from onyx.server.query_and_chat.streaming_models import GeneratedImage


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class FinalImageGenerationResponse(BaseModel):
    generated_images: list[GeneratedImage]
