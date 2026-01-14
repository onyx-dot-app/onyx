import json
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class VertexCredentials(BaseModel):
    vertex_credentials: str
    vertex_location: str
    project_id: str


class VertexImageGenerationProvider(ImageGenerationProvider):
    NAME = "vertex_ai"

    def __init__(
        self,
        vertex_credentials: VertexCredentials,
    ):
        self._vertex_credentials = vertex_credentials

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
    ) -> "VertexImageGenerationProvider":
        vertex_credentials = _parse_to_vertex_credentials(credentials)

        return cls(
            vertex_credentials=vertex_credentials,
        )

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        **kwargs: Any,
    ) -> "ImageGenerationResponse":
        from litellm import image_generation

        try:
            x = image_generation(
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
        except Exception as e:
            print(str(e))
            raise ImageProviderCredentialsError(f"Error generating image: {e}")

        return x


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

    return VertexCredentials(
        vertex_credentials=vertex_credentials,
        vertex_location=vertex_location,
        project_id=vertex_project,
    )
