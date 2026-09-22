from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.llm.well_known_providers.constants import (
    VERTEX_AUTH_METHOD_KWARG,
    VERTEX_AUTH_METHOD_SERVICE_ACCOUNT,
    VERTEX_AUTH_METHOD_WORKLOAD_IDENTITY,
    VERTEX_CREDENTIALS_FILE_KWARG,
    VERTEX_LOCATION_KWARG,
    VERTEX_PROJECT_KWARG,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class VertexCredentials(BaseModel):
    # None when authenticating via Workload Identity (ambient GKE credentials).
    vertex_credentials: str | None
    vertex_location: str
    project_id: str
    use_workload_identity: bool = False


class VertexImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        vertex_credentials: VertexCredentials,
    ):
        self._vertex_credentials = vertex_credentials.vertex_credentials
        self._vertex_location = vertex_credentials.vertex_location
        self._vertex_project = vertex_credentials.project_id
        self._use_workload_identity = vertex_credentials.use_workload_identity

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
        del quality, kwargs  # Google has no equivalent image quality parameter.
        from google import genai
        from google.genai import types as genai_types
        from pydantic_ai import BinaryImage, ImageGenerator
        from pydantic_ai.images.google import GoogleImageGenerationModel
        from pydantic_ai.providers.google import GoogleProvider

        from onyx.image_gen.interfaces import ImageGenerationResponse, ImageObject
        from onyx.image_gen.providers.pydantic_images import image_response

        credentials: Any
        if self._use_workload_identity:
            import google.auth

            # Ambient GKE credentials (pod's bound GCP service account).
            credentials, _ = google.auth.default(scopes=VERTEX_SCOPES)
        else:
            from google.oauth2 import service_account

            if self._vertex_credentials is None:
                raise ImageProviderCredentialsError("Vertex credentials are required")
            service_account_info = json.loads(self._vertex_credentials)
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=VERTEX_SCOPES,
            )

        client = genai.Client(
            vertexai=True,
            project=self._vertex_project,
            location=self._vertex_location,
            credentials=credentials,
        )

        model_name = model.removeprefix("vertex_ai/")
        try:
            with traced_llm_call(
                flow=LLMFlow.IMAGE_EDIT
                if reference_images
                else LLMFlow.IMAGE_GENERATION,
                model=model_name,
                provider="vertex_ai",
                image_count=n,
                input_messages=[{"role": "user", "content": prompt}],
            ):
                if "imagen" in model_name:
                    if reference_images:
                        raise ValueError("Imagen reference editing is not supported")
                    response = client.models.generate_images(
                        model=model_name,
                        prompt=prompt,
                        config=genai_types.GenerateImagesConfig(
                            number_of_images=n,
                            aspect_ratio=_map_size_to_aspect_ratio(size),
                        ),
                    )
                    return ImageGenerationResponse(
                        created=int(datetime.now().timestamp()),
                        data=[
                            ImageObject(
                                b64_json=base64.b64encode(
                                    item.image.image_bytes
                                ).decode()
                            )
                            for item in response.generated_images or []
                            if item.image and item.image.image_bytes
                        ],
                    )
                generator = ImageGenerator(
                    GoogleImageGenerationModel(
                        model_name, provider=GoogleProvider(client=client)
                    )
                )
                generated_data: list[ImageObject] = []
                for _ in range(n):
                    result = generator.generate_sync(
                        prompt,
                        images=[
                            BinaryImage(data=image.data, media_type=image.mime_type)
                            for image in reference_images
                        ]
                        if reference_images
                        else None,
                        settings={"aspect_ratio": _map_size_to_aspect_ratio(size)},
                    )
                    generated_data.extend(image_response(result).data)
                if not generated_data:
                    raise RuntimeError("No image data returned from Vertex AI.")
                return ImageGenerationResponse(
                    created=int(datetime.now().timestamp()), data=generated_data
                )
        finally:
            client.close()


def _map_size_to_aspect_ratio(
    size: str,
) -> Literal["1:1", "16:9", "9:16", "3:2", "2:3"]:
    ratios: dict[str, Literal["1:1", "16:9", "9:16", "3:2", "2:3"]] = {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "1536x1024": "3:2",
        "1024x1536": "2:3",
    }
    return ratios.get(size, "1:1")


def _parse_to_vertex_credentials(
    credentials: ImageGenerationProviderCredentials,
) -> VertexCredentials:
    custom_config = credentials.custom_config

    if not custom_config:
        raise ImageProviderCredentialsError("Custom config is required")

    vertex_location = custom_config.get(VERTEX_LOCATION_KWARG)
    if not vertex_location:
        raise ImageProviderCredentialsError("Vertex location is required")

    # Missing auth method is treated as service_account_json for backwards
    # compatibility with configs created before this field existed.
    auth_method = custom_config.get(
        VERTEX_AUTH_METHOD_KWARG, VERTEX_AUTH_METHOD_SERVICE_ACCOUNT
    )

    if auth_method == VERTEX_AUTH_METHOD_WORKLOAD_IDENTITY:
        # No service account JSON: authenticate via ambient GKE credentials. The
        # project can't be inferred from a key file, so it must be explicit.
        vertex_project = (custom_config.get(VERTEX_PROJECT_KWARG) or "").strip()
        if not vertex_project:
            raise ImageProviderCredentialsError(
                "Project ID is required when using Workload Identity"
            )
        return VertexCredentials(
            vertex_credentials=None,
            vertex_location=vertex_location,
            project_id=vertex_project,
            use_workload_identity=True,
        )

    vertex_credentials = custom_config.get(VERTEX_CREDENTIALS_FILE_KWARG)
    if not vertex_credentials:
        raise ImageProviderCredentialsError("Vertex credentials are required")

    try:
        vertex_json = json.loads(vertex_credentials)
    except json.JSONDecodeError as e:
        raise ImageProviderCredentialsError(
            "Vertex credentials must be valid JSON"
        ) from e
    vertex_project = vertex_json.get("project_id")

    if not vertex_project:
        raise ImageProviderCredentialsError("Project ID is required")

    return VertexCredentials(
        vertex_credentials=vertex_credentials,
        vertex_location=vertex_location,
        project_id=vertex_project,
        use_workload_identity=False,
    )
