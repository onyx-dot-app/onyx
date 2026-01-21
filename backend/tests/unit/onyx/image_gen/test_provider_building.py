import json

import pytest

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.providers.azure_img_gen import AzureImageGenerationProvider
from onyx.image_gen.providers.openai_img_gen import OpenAIImageGenerationProvider
from onyx.image_gen.providers.vertex_img_gen import VertexImageGenerationProvider

OPENAI_PROVIDER = "openai"
AZURE_PROVIDER = "azure"
VERTEX_PROVIDER = "vertex_ai"


def _get_default_image_gen_creds() -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(
        api_key=None,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )


def test_request_provider_that_no_exist() -> None:
    provider = "nonexistent"
    credentials = _get_default_image_gen_creds()

    with pytest.raises(ValueError):
        get_image_generation_provider(provider, credentials)


def test_build_openai_provider_from_api_key_and_base() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test"
    credentials.api_base = "test"

    provider = OPENAI_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, OpenAIImageGenerationProvider)
    assert image_gen_provider._api_key == "test"
    assert image_gen_provider._api_base == "test"


def test_build_openai_provider_fails_no_api_key() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_base = "test"

    provider = OPENAI_PROVIDER

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(provider, credentials)


def test_build_azure_provider_from_api_key_and_base_and_version() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test"
    credentials.api_base = "test"
    credentials.api_version = "test"

    provider = AZURE_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, AzureImageGenerationProvider)
    assert image_gen_provider._api_key == "test"
    assert image_gen_provider._api_base == "test"
    assert image_gen_provider._api_version == "test"


def test_build_azure_provider_fails_missing_credential() -> None:
    azure_required = [
        "api_key",
        "api_base",
        "api_version",
    ]

    default_creds = _get_default_image_gen_creds()
    default_creds.api_key = "test"
    default_creds.api_base = "test"
    default_creds.api_version = "test"

    for attribute in azure_required:
        credentials = default_creds.model_copy()
        setattr(credentials, attribute, None)

        with pytest.raises(ImageProviderCredentialsError):
            get_image_generation_provider(AZURE_PROVIDER, credentials)


def test_build_vertex_provider_from_credentials() -> None:
    credentials = _get_default_image_gen_creds()

    vertex_credentials = {
        "project_id": "demo_project_1",
        "private_key_id": "test",
    }

    vertex_json = json.dumps(vertex_credentials)
    credentials.custom_config = {
        "vertex_credentials": vertex_json,
        "vertex_location": "global",
    }
    provider = VERTEX_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, VertexImageGenerationProvider)
    assert image_gen_provider._vertex_credentials == vertex_json
    assert image_gen_provider._vertex_location == "global"
    assert image_gen_provider._vertex_project == "demo_project_1"


def test_build_vertex_provider_with_missing_project_id() -> None:
    credentials = _get_default_image_gen_creds()

    vertex_credentials = {
        "private_key_id": "test",
    }

    vertex_json = json.dumps(vertex_credentials)
    credentials.custom_config = {
        "vertex_credentials": vertex_json,
        "vertex_location": "global",
    }

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider("vertex_ai", credentials)
