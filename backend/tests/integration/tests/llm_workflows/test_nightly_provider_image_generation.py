import base64
from uuid import uuid4

from onyx.server.manage.image_generation.api import _get_test_quality_for_model
from onyx.utils.b64 import get_image_type_from_bytes
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.llm_workflows.test_nightly_provider_chat_workflow import (
    NightlyProviderConfig,
    _assert_integration_mode_enabled,
    _create_provider_payload,
    _default_api_base_for_provider,
    _load_provider_config,
    _skip_or_fail,
    _validate_provider_config,
)

# Azure serves images from per-model deployments, which the chat matrix does not configure.
_PROVIDERS_WITHOUT_SHARED_IMAGE_ACCESS = frozenset({"azure"})
_GENERATE_TIMEOUT_S = 300


def _create_llm_provider(admin_user: DATestUser, config: NightlyProviderConfig) -> int:
    model_name = config.model_names[0]
    payload = _create_provider_payload(
        provider=config.provider,
        provider_name=f"nightly-image-{config.provider}-{uuid4().hex[:12]}",
        model_name=model_name,
        api_key=config.api_key,
        api_base=config.api_base or _default_api_base_for_provider(config.provider),
        api_version=config.api_version,
        deployment_name=config.deployment_name,
        custom_config=config.custom_config,
    )
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json=payload,
    )
    assert response.status_code == 200, (
        f"Provider creation failed for provider={config.provider}: "
        f"{response.status_code} {response.text}"
    )
    return response.json()["id"]


def _recommended_image_models(
    admin_user: DATestUser, llm_provider_id: int
) -> list[str]:
    response = client.get(
        f"{API_SERVER_URL}/admin/image-generation/llm-providers",
        headers=admin_user.headers,
    )
    response.raise_for_status()
    for llm_provider in response.json():
        if llm_provider["llm_provider_id"] == llm_provider_id:
            return [m["name"] for m in llm_provider["models"] if m["is_recommended"]]
    return []


def _link_and_generate(
    admin_user: DATestUser, llm_provider_id: int, model_name: str
) -> None:
    link_response = client.post(
        f"{API_SERVER_URL}/admin/image-generation/config/link",
        headers=admin_user.headers,
        json={
            "llm_provider_id": llm_provider_id,
            "model_name": model_name,
            "is_default": True,
        },
    )
    assert link_response.status_code == 200, (
        f"link failed: {link_response.status_code} {link_response.text}"
    )
    image_provider_id = link_response.json()["image_provider_id"]
    try:
        generate_response = client.post(
            f"{API_SERVER_URL}/image-generation/generate",
            headers=admin_user.headers,
            json={
                "prompt": "A red circle on a white background",
                "n": 1,
                "quality": _get_test_quality_for_model(model_name),
            },
            timeout=_GENERATE_TIMEOUT_S,
        )
        assert generate_response.status_code == 200, (
            f"generate failed: {generate_response.status_code} {generate_response.text}"
        )
        body = generate_response.json()
        assert "error_code" not in body, f"generate error: {body}"
        images = body["images"]
        assert images, "no images returned"
        image_bytes = base64.b64decode(images[0]["data_base64"])
        get_image_type_from_bytes(image_bytes)
    finally:
        client.delete(
            f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}",
            headers=admin_user.headers,
        )


def test_nightly_provider_image_generation(admin_user: DATestUser) -> None:
    """Real generation for every recommended image model on the provider."""
    _assert_integration_mode_enabled()
    config = _load_provider_config()
    _validate_provider_config(config)
    if config.provider in _PROVIDERS_WITHOUT_SHARED_IMAGE_ACCESS:
        _skip_or_fail(False, f"provider={config.provider} has no shared image access")

    llm_provider_id = _create_llm_provider(admin_user, config)
    failures: list[str] = []
    try:
        model_names = _recommended_image_models(admin_user, llm_provider_id)
        if not model_names:
            _skip_or_fail(
                False, f"provider={config.provider} has no catalog image models"
            )
        for model_name in model_names:
            try:
                _link_and_generate(admin_user, llm_provider_id, model_name)
            except Exception as exc:
                failures.append(
                    f"provider={config.provider} model={model_name} "
                    f"error={type(exc).__name__}: {exc}"
                )
    finally:
        client.delete(
            f"{API_SERVER_URL}/admin/llm/provider/{llm_provider_id}",
            headers=admin_user.headers,
        )

    if failures:
        _skip_or_fail(
            config.strict,
            "Nightly provider image generation failures:\n" + "\n".join(failures),
        )
