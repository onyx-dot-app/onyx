import uuid
from typing import Any

import pytest
import requests
from requests.models import Response

from onyx.llm.model_name_parser import parse_litellm_model_name
from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import litellm_thinks_model_supports_image_input
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _get_provider_by_id(admin_user: DATestUser, provider_id: str) -> dict | None:
    """Utility function to fetch an LLM provider by ID"""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    providers = response.json()
    return next((p for p in providers if p["id"] == provider_id), None)


def assert_response_is_equivalent(
    admin_user: DATestUser,
    response: Response,
    default_model_name: str,
    model_configurations: list[ModelConfigurationUpsertRequest],
    api_key: str | None = None,
) -> None:
    assert response.status_code == 200
    created_provider = response.json()

    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is not None

    assert provider_data["default_model_name"] == default_model_name
    assert provider_data["personas"] == []

    def fill_max_input_tokens_and_supports_image_input(
        req: ModelConfigurationUpsertRequest,
    ) -> dict[str, Any]:
        provider_name = created_provider["provider"]
        # Match how ModelConfigurationView.from_model builds the key for parsing
        model_key = req.name
        if provider_name and not model_key.startswith(f"{provider_name}/"):
            model_key = f"{provider_name}/{model_key}"
        parsed = parse_litellm_model_name(model_key)

        # Include region in display name for Bedrock cross-region models (matches from_model)
        display_name = (
            f"{parsed.display_name} ({parsed.region})"
            if parsed.region
            else parsed.display_name
        )

        filled_with_max_input_tokens = ModelConfigurationUpsertRequest(
            name=req.name,
            is_visible=req.is_visible,
            max_input_tokens=req.max_input_tokens
            or get_max_input_tokens(model_name=req.name, model_provider=provider_name),
        )
        return {
            **filled_with_max_input_tokens.model_dump(),
            "supports_image_input": litellm_thinks_model_supports_image_input(
                req.name, provider_name
            ),
            "supports_reasoning": model_is_reasoning_model(req.name, provider_name),
            "display_name": display_name,
            "provider_display_name": parsed.provider_display_name,
            "vendor": parsed.vendor,
            "region": parsed.region,
            "version": parsed.version,
        }

    # Compare model configurations by name (order-independent)
    actual_by_name = {
        config["name"]: config for config in provider_data["model_configurations"]
    }
    expected_by_name = {
        config.name: fill_max_input_tokens_and_supports_image_input(config)
        for config in model_configurations
    }

    assert set(actual_by_name.keys()) == set(expected_by_name.keys()), (
        f"Model names don't match. "
        f"Actual: {set(actual_by_name.keys())}, Expected: {set(expected_by_name.keys())}"
    )

    for name in actual_by_name:
        actual_config = actual_by_name[name]
        expected_config = expected_by_name[name]
        assert actual_config == expected_config, (
            f"Config mismatch for {name}:\n"
            f"Actual: {actual_config}\n"
            f"Expected: {expected_config}"
        )

    # test that returned key is sanitized
    if api_key:
        assert provider_data["api_key"] == api_key


# Test creating an LLM Provider with some various model-configurations.
@pytest.mark.parametrize(
    "default_model_name, model_configurations, expected",
    [
        # Test the case in which a basic model-configuration is passed.
        (
            "gpt-4",
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4", is_visible=True, max_input_tokens=4096
                )
            ],
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4", is_visible=True, max_input_tokens=4096
                )
            ],
        ),
        # Test the case in which multiple model-configuration are passed.
        (
            "gpt-4",
            [
                ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
            ],
            [
                ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
            ],
        ),
        # Test the case in which duplicate model-configuration are passed.
        (
            "gpt-4",
            [ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True)] * 4,
            [ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True)],
        ),
        # Test the case in which no model-configurations are passed.
        # In this case, a model-configuration for "gpt-4" should be inferred
        # (`ModelConfiguration(name="gpt-4", is_visible=True, max_input_tokens=None)`).
        (
            "gpt-4",
            [],
            [ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True)],
        ),
        # Test the case in which the default-model-name is not contained inside of the model-configurations list.
        # Once again, in this case, a model-configuration for "gpt-4" should be inferred
        # (`ModelConfiguration(name="gpt-4", is_visible=True, max_input_tokens=None)`).
        (
            "gpt-4",
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4o", is_visible=True, max_input_tokens=4096
                )
            ],
            [
                ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                ModelConfigurationUpsertRequest(
                    name="gpt-4o", is_visible=True, max_input_tokens=4096
                ),
            ],
        ),
    ],
)
def test_create_llm_provider(
    reset: None,
    default_model_name: str,
    model_configurations: list[ModelConfigurationUpsertRequest],
    expected: list[ModelConfigurationUpsertRequest],
) -> None:
    admin_user = UserManager.create(name="admin_user")

    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": str(uuid.uuid4()),
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": default_model_name,
            "model_configurations": [
                model_configuration.model_dump()
                for model_configuration in model_configurations
            ],
            "is_public": True,
            "groups": [],
        },
    )

    assert_response_is_equivalent(
        admin_user,
        response,
        default_model_name,
        expected,
        "sk-0****0000",
    )


# Test creating a new LLM Provider with some given model-configurations, then performing some arbitrary update on it.
@pytest.mark.parametrize(
    "initial, initial_expected, updated, updated_expected",
    [
        # Test the case in which a basic model-configuration is passed, but then it's updated to have *NO* max-input-tokens.
        (
            (
                "gpt-4",
                [
                    ModelConfigurationUpsertRequest(
                        name="gpt-4", is_visible=True, max_input_tokens=4096
                    )
                ],
            ),
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4", is_visible=True, max_input_tokens=4096
                )
            ],
            (
                "gpt-4",
                [ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True)],
            ),
            [ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True)],
        ),
        # Test the case where we insert 2 model-configurations, and then in the update the first,
        # we update one and delete the second.
        (
            (
                "gpt-4",
                [
                    ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, max_input_tokens=4096
                    ),
                ],
            ),
            [
                ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                ModelConfigurationUpsertRequest(
                    name="gpt-4o", is_visible=True, max_input_tokens=4096
                ),
            ],
            (
                "gpt-4",
                [
                    ModelConfigurationUpsertRequest(
                        name="gpt-4", is_visible=True, max_input_tokens=4096
                    )
                ],
            ),
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4", is_visible=True, max_input_tokens=4096
                )
            ],
        ),
    ],
)
def test_update_model_configurations(
    reset: None,
    initial: tuple[str, list[ModelConfigurationUpsertRequest]],
    initial_expected: list[ModelConfigurationUpsertRequest],
    updated: tuple[str, list[ModelConfigurationUpsertRequest]],
    updated_expected: list[ModelConfigurationUpsertRequest],
) -> None:
    admin_user = UserManager.create(name="admin_user")

    default_model_name, model_configurations = initial
    updated_default_model_name, updated_model_configurations = updated

    name = str(uuid.uuid4())

    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": name,
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": default_model_name,
            "model_configurations": [
                model_configuration.dict()
                for model_configuration in model_configurations
            ],
            "is_public": True,
            "groups": [],
            "api_key_changed": True,
        },
    )
    created_provider = response.json()
    assert_response_is_equivalent(
        admin_user,
        response,
        default_model_name,
        initial_expected,
    )

    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "id": created_provider["id"],
            "name": name,
            "provider": created_provider["provider"],
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "default_model_name": updated_default_model_name,
            "model_configurations": [
                model_configuration.dict()
                for model_configuration in updated_model_configurations
            ],
            "is_public": True,
            "groups": [],
        },
    )
    assert_response_is_equivalent(
        admin_user,
        response,
        updated_default_model_name,
        updated_expected,
        "sk-0****0000",
    )

    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "id": created_provider["id"],
            "name": name,
            "provider": created_provider["provider"],
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "default_model_name": updated_default_model_name,
            "model_configurations": [
                model_configuration.dict()
                for model_configuration in updated_model_configurations
            ],
            "is_public": True,
            "groups": [],
            "api_key_changed": True,
        },
    )
    assert_response_is_equivalent(
        admin_user,
        response,
        updated_default_model_name,
        updated_expected,
        "sk-0****0001",
    )


@pytest.mark.parametrize(
    "default_model_name, model_configurations",
    [
        (
            "gpt-4",
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-4", is_visible=True, max_input_tokens=4096
                )
            ],
        ),
        (
            "gpt-4",
            [
                ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
            ],
        ),
    ],
)
def test_delete_llm_provider(
    reset: None,
    default_model_name: str,
    model_configurations: list[ModelConfigurationUpsertRequest],
) -> None:
    admin_user = UserManager.create(name="admin_user")

    # Create a provider
    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": "test-provider-delete",
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": default_model_name,
            "model_configurations": [
                model_configuration.dict()
                for model_configuration in model_configurations
            ],
            "is_public": True,
            "groups": [],
        },
    )
    created_provider = response.json()
    assert response.status_code == 200

    # Delete the provider
    response = requests.delete(
        f"{API_SERVER_URL}/admin/llm/provider/{created_provider['id']}",
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Verify provider is deleted by checking it's not in the list
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is None


def test_model_visibility_preserved_on_edit(reset: None) -> None:
    """
    Test that model visibility flags are correctly preserved when editing an LLM provider.

    This test verifies the fix for the bug where editing a provider with specific visible models
    would incorrectly map visibility flags when the provider's model list differs from the
    descriptor's default model list.

    Scenario:
    1. Create a provider with 3 models, 2 visible
    2. Edit the provider to change visibility (make all 3 visible)
    3. Verify all 3 models are now visible
    4. Edit again to make only 1 visible
    5. Verify only 1 is visible
    """
    admin_user = UserManager.create(name="admin_user")

    # Initial model configurations: 2 visible, 1 hidden
    model_configs = [
        ModelConfigurationUpsertRequest(
            name="gpt-4o",
            is_visible=True,
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4o-mini",
            is_visible=True,
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4-turbo",
            is_visible=False,
            max_input_tokens=None,
            supports_image_input=None,
        ),
    ]

    # Create the provider
    create_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": "test-visibility-provider",
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": "gpt-4o",
            "model_configurations": [config.dict() for config in model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response.status_code == 200
    created_provider = create_response.json()

    # Verify initial state: 2 visible models
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is not None
    visible_models = [
        model for model in provider_data["model_configurations"] if model["is_visible"]
    ]
    assert len(visible_models) == 2
    assert any(m["name"] == "gpt-4o" for m in visible_models)
    assert any(m["name"] == "gpt-4o-mini" for m in visible_models)

    # Edit 1: Make all 3 models visible
    edit_configs_all_visible = [
        ModelConfigurationUpsertRequest(
            name="gpt-4o",
            is_visible=True,
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4o-mini",
            is_visible=True,
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4-turbo",
            is_visible=True,  # Now visible
            max_input_tokens=None,
            supports_image_input=None,
        ),
    ]

    edit_response_1 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        headers=admin_user.headers,
        json={
            "name": "test-visibility-provider",
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": "gpt-4o",
            "model_configurations": [
                config.dict() for config in edit_configs_all_visible
            ],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert edit_response_1.status_code == 200

    # Verify all 3 models are now visible
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is not None
    visible_models = [
        model for model in provider_data["model_configurations"] if model["is_visible"]
    ]
    assert len(visible_models) == 3

    # Edit 2: Make only 1 model visible
    edit_configs_one_visible = [
        ModelConfigurationUpsertRequest(
            name="gpt-4o",
            is_visible=True,  # Only this one visible
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4o-mini",
            is_visible=False,
            max_input_tokens=None,
            supports_image_input=None,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4-turbo",
            is_visible=False,
            max_input_tokens=None,
            supports_image_input=None,
        ),
    ]

    edit_response_2 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        headers=admin_user.headers,
        json={
            "name": "test-visibility-provider",
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": "gpt-4o",
            "model_configurations": [
                config.dict() for config in edit_configs_one_visible
            ],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert edit_response_2.status_code == 200

    # Verify only 1 model is visible
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is not None
    visible_models = [
        model for model in provider_data["model_configurations"] if model["is_visible"]
    ]
    assert len(visible_models) == 1
    assert visible_models[0]["name"] == "gpt-4o"
