from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class VertexCredentials(BaseModel):
    vertex_credentials: str
    vertex_location: str
    project_id: str


class VertexImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        vertex_credentials: VertexCredentials,
    ):
        self._vertex_credentials = vertex_credentials.vertex_credentials
        self._vertex_location = vertex_credentials.vertex_location
        self._vertex_project = vertex_credentials.project_id

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        try:
            _parse_to_vertex_credentials(credentials)
            return True
        except ImageProviderCredentialsError:
            return False

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> VertexImageGenerationProvider:
        vertex_credentials = _parse_to_vertex_credentials(credentials)

        return cls(
            vertex_credentials=vertex_credentials,
        )

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        # Gemini image editing supports up to 14 input images.
        return 14

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        if reference_images:
            return self._generate_image_with_reference_images(
                prompt=prompt,
                model=model,
                size=size,
                n=n,
                reference_images=reference_images,
            )

        from litellm import image_generation

        return image_generation(
            prompt=prompt,
            model=model,
            size=size,
            n=n,
            quality=quality,
            vertex_location=self._vertex_location,
            vertex_credentials=self._vertex_credentials,
            vertex_project=self._vertex_project,
            **kwargs,
        )

    def _generate_image_with_reference_images(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        reference_images: list[ReferenceImage],
    ) -> ImageGenerationResponse:
        from google import genai
        from google.genai import types as genai_types
        from google.oauth2 import service_account
        from litellm.types.utils import ImageObject
        from litellm.types.utils import ImageResponse

        service_account_info = json.loads(self._vertex_credentials)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

        client = genai.Client(
            vertexai=True,
            project=self._vertex_project,
            location=self._vertex_location,
            credentials=credentials,
        )

        parts: list[genai_types.Part] = [
            genai_types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
            for image in reference_images
        ]
        parts.append(genai_types.Part.from_text(text=prompt))

        config = genai_types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            candidate_count=max(1, n),
            image_config=genai_types.ImageConfig(
                aspect_ratio=_map_size_to_aspect_ratio(size)
            ),
        )
        model_name = model.replace("vertex_ai/", "")
        response = client.models.generate_content(
            model=model_name,
            contents=genai_types.Content(
                role="user",
                parts=parts,
            ),
            config=config,
        )

        generated_data: list[ImageObject] = []
        for candidate in response.candidates or []:
            candidate_content = candidate.content
            if not candidate_content:
                continue

            for part in candidate_content.parts or []:
                inline_data = part.inline_data
                if not inline_data or inline_data.data is None:
                    continue

                if isinstance(inline_data.data, bytes):
                    b64_json = base64.b64encode(inline_data.data).decode("utf-8")
                elif isinstance(inline_data.data, str):
                    b64_json = inline_data.data
                else:
                    continue

                generated_data.append(
                    ImageObject(
                        b64_json=b64_json,
                        revised_prompt=prompt,
                    )
                )

        if not generated_data:
            raise RuntimeError("No image data returned from Vertex AI.")

        return ImageResponse(
            created=int(datetime.now().timestamp()),
            data=generated_data,
        )


def _map_size_to_aspect_ratio(size: str) -> str:
    return {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "1536x1024": "3:2",
        "1024x1536": "2:3",
    }.get(size, "1:1")


def _parse_to_vertex_credentials(
    credentials: ImageGenerationProviderCredentials,
) -> VertexCredentials:
    custom_config = credentials.custom_config

    if not custom_config:
        raise ImageProviderCredentialsError("Custom config is required")

    vertex_credentials = custom_config.get("vertex_credentials")
    vertex_location = custom_config.get("vertex_location")

    if not vertex_credentials:
        raise ImageProviderCredentialsError("Vertex credentials are required")

    if not vertex_location:
        raise ImageProviderCredentialsError("Vertex location is required")

    vertex_json = json.loads(vertex_credentials)
    vertex_project = vertex_json.get("project_id")

    if not vertex_project:
        raise ImageProviderCredentialsError("Project ID is required")

    return VertexCredentials(
        vertex_credentials=vertex_credentials,
        vertex_location=vertex_location,
        project_id=vertex_project,
    )
