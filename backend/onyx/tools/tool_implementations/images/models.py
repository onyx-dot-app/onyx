from typing import Literal

from pydantic import BaseModel, Field, field_validator

from onyx.image_gen.interfaces import ImageShape
from onyx.tools.models import GeneratedImage
from onyx.utils.text_processing import unique_stripped


class ImageGenerationResponse(BaseModel):
    revised_prompt: str
    image_data: str


class ImageResult(BaseModel):
    """A generated image as the model reads it: the file id that a later edit
    uses, and the prompt the provider used."""

    file_id: str
    revised_prompt: str


class FinalImageGenerationResponse(BaseModel):
    type: Literal["image_generation_result"] = "image_generation_result"
    generated_images: list[GeneratedImage]


class ImageGenerationArguments(BaseModel):
    prompt: str = Field(description="Prompt used to generate the image")
    # A Literal, unlike the enum, keeps the strict schema free of references.
    shape: Literal[ImageShape.SQUARE, ImageShape.PORTRAIT, ImageShape.LANDSCAPE] = (
        Field(
            default=ImageShape.SQUARE,
            description=(
                "Use null for the default square shape."
                " Image shape: 'square', 'portrait', or 'landscape'."
            ),
        )
    )
    reference_image_file_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Optional file_ids of existing images to edit or use as reference;"
            " the first is the primary edit source."
            " Get file_ids from `[attached image — file_id: <id>]` tags on"
            " user-attached images or from prior generate_image tool responses."
            " Use null for a fresh, unrelated generation."
        ),
    )

    @field_validator("reference_image_file_ids")
    @classmethod
    def clean_reference_image_file_ids(cls, file_ids: list[str]) -> list[str]:
        """Strip each file ID and drop empty and repeated ones. The first ID
        stays first, as it is the primary edit source."""
        return unique_stripped(file_ids)
