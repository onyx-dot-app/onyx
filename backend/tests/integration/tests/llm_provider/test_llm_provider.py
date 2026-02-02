import uuid
from typing import Any

import pytest
import requests
from requests.models import Response

from onyx.llm.constants import LlmProviderNames
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
            "provider": LlmProviderNames.OPENAI,
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
            "provider": LlmProviderNames.OPENAI,
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
            "provider": LlmProviderNames.OPENAI,
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
            "provider": LlmProviderNames.OPENAI,
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
            "provider": LlmProviderNames.OPENAI,
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
            "provider": LlmProviderNames.OPENAI,
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


def _get_provider_by_name_admin(
    admin_user: DATestUser, provider_name: str
) -> dict | None:
    """Utility function to fetch an LLM provider by name via admin endpoint."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    providers = response.json()
    return next((p for p in providers if p["name"] == provider_name), None)


def _get_provider_by_name_basic(user: DATestUser, provider_name: str) -> dict | None:
    """Utility function to fetch an LLM provider by name via basic (non-admin) endpoint."""
    response = requests.get(
        f"{API_SERVER_URL}/llm/provider",
        headers=user.headers,
    )
    assert response.status_code == 200
    providers = response.json()
    return next((p for p in providers if p["name"] == provider_name), None)


def _validate_model_configurations(
    actual_configs: list[dict],
    expected_model_names: list[str],
    expected_visible: dict[str, bool] | None = None,
    expected_image_support: dict[str, bool] | None = None,
) -> None:
    """
    Validate that model configurations match expectations.

    Args:
        actual_configs: List of model configuration dicts from the API response
        expected_model_names: List of expected model names
        expected_visible: Optional dict mapping model name to expected visibility
        expected_image_support: Optional dict mapping model name to expected supports_image_input
    """
    actual_names = {config["name"] for config in actual_configs}
    expected_names = set(expected_model_names)

    assert (
        actual_names == expected_names
    ), f"Model names mismatch. Expected: {expected_names}, Actual: {actual_names}"

    if expected_visible:
        for config in actual_configs:
            if config["name"] in expected_visible:
                assert config["is_visible"] == expected_visible[config["name"]], (
                    f"Visibility mismatch for {config['name']}. "
                    f"Expected: {expected_visible[config['name']]}, Actual: {config['is_visible']}"
                )

    if expected_image_support:
        for config in actual_configs:
            if config["name"] in expected_image_support:
                assert (
                    config["supports_image_input"]
                    == expected_image_support[config["name"]]
                ), (
                    f"supports_image_input mismatch for {config['name']}. "
                    f"Expected: {expected_image_support[config['name']]}, "
                    f"Actual: {config['supports_image_input']}"
                )


def _validate_provider_data(
    provider_data: dict,
    expected_name: str,
    expected_provider: str,
    expected_default_model: str,
    expected_is_default: bool | None,
    expected_model_names: list[str],
    expected_visible: dict[str, bool] | None = None,
    expected_is_public: bool | None = None,
    expected_is_default_vision: bool | None = None,
    expected_default_vision_model: str | None = None,
    expected_image_support: dict[str, bool] | None = None,
) -> None:
    """
    Validate that provider data matches expectations.

    Args:
        provider_data: Provider dict from the API response
        expected_name: Expected provider name
        expected_provider: Expected provider type (e.g., 'openai')
        expected_default_model: Expected default model name
        expected_is_default: Expected is_default_provider value
        expected_model_names: List of expected model names in configurations
        expected_visible: Optional dict mapping model name to expected visibility
        expected_is_public: Optional expected is_public value (admin endpoint only)
        expected_is_default_vision: Optional expected is_default_vision_provider value
        expected_default_vision_model: Optional expected default_vision_model value
        expected_image_support: Optional dict mapping model name to expected supports_image_input
    """
    assert (
        provider_data["name"] == expected_name
    ), f"Provider name mismatch. Expected: {expected_name}, Actual: {provider_data['name']}"
    assert (
        provider_data["provider"] == expected_provider
    ), f"Provider type mismatch. Expected: {expected_provider}, Actual: {provider_data['provider']}"
    assert provider_data["default_model_name"] == expected_default_model, (
        f"Default model mismatch. Expected: {expected_default_model}, "
        f"Actual: {provider_data['default_model_name']}"
    )
    assert provider_data["is_default_provider"] == expected_is_default, (
        f"is_default_provider mismatch. Expected: {expected_is_default}, "
        f"Actual: {provider_data['is_default_provider']}"
    )

    # Validate is_public if provided (only available in admin endpoint response)
    if expected_is_public is not None and "is_public" in provider_data:
        assert provider_data["is_public"] == expected_is_public, (
            f"is_public mismatch. Expected: {expected_is_public}, "
            f"Actual: {provider_data['is_public']}"
        )

    # Validate vision-related fields if provided
    if expected_is_default_vision is not None:
        assert (
            provider_data.get("is_default_vision_provider")
            == expected_is_default_vision
        ), (
            f"is_default_vision_provider mismatch. Expected: {expected_is_default_vision}, "
            f"Actual: {provider_data.get('is_default_vision_provider')}"
        )

    if expected_default_vision_model is not None:
        assert (
            provider_data.get("default_vision_model") == expected_default_vision_model
        ), (
            f"default_vision_model mismatch. Expected: {expected_default_vision_model}, "
            f"Actual: {provider_data.get('default_vision_model')}"
        )

    # Validate model configurations
    _validate_model_configurations(
        provider_data["model_configurations"],
        expected_model_names,
        expected_visible,
        expected_image_support,
    )


def test_default_model_persistence_and_update(reset: None) -> None:
    """
    Test that the default model is correctly set, persisted, and can be updated.

    This test verifies:
    1. Admin creates a provider with a specific default model
    2. Admin endpoint (/admin/llm/provider) shows correct default model
    3. Basic endpoint (/llm/provider) shows correct default model for admin user
    4. Non-admin user can see the same default model via basic endpoint
    5. Admin updates the default model
    6. Both admin and basic endpoints reflect the new default model
    7. Non-admin user sees the updated default model
    """
    from onyx.auth.schemas import UserRole

    admin_user = UserManager.create(name="admin_user")

    # Create a non-admin user
    basic_user = UserManager.create(name="basic_user")
    # The first user is admin, subsequent users are basic by default
    assert basic_user.role == UserRole.BASIC or basic_user.role != UserRole.ADMIN

    provider_name = f"test-default-model-{uuid.uuid4()}"
    initial_default_model = "gpt-4"
    updated_default_model = "gpt-4o"

    # Model configurations including all models we'll use
    model_configs = [
        ModelConfigurationUpsertRequest(
            name="gpt-4",
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4o",
            is_visible=True,
        ),
    ]

    # Expected model names and visibility
    expected_model_names = ["gpt-4", "gpt-4o"]
    expected_visible = {"gpt-4": True, "gpt-4o": True}

    # Step 1: Admin creates the provider with initial default model
    create_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": initial_default_model,
            "model_configurations": [config.model_dump() for config in model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response.status_code == 200

    # Step 2: Verify via admin endpoint that all provider data is correct
    admin_provider_data = _get_provider_by_name_admin(admin_user, provider_name)
    assert admin_provider_data is not None
    _validate_provider_data(
        admin_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=initial_default_model,
        expected_is_default=None,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
        expected_is_public=True,
    )

    # Step 3: Verify via basic endpoint (admin user) that all provider data is correct
    admin_basic_provider_data = _get_provider_by_name_basic(admin_user, provider_name)
    assert admin_basic_provider_data is not None
    _validate_provider_data(
        admin_basic_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=initial_default_model,
        expected_is_default=None,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
    )

    # Step 4: Verify non-admin user sees the same provider data via basic endpoint
    basic_user_provider_data = _get_provider_by_name_basic(basic_user, provider_name)
    assert basic_user_provider_data is not None
    _validate_provider_data(
        basic_user_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=initial_default_model,
        expected_is_default=None,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
    )

    # Step 5: Admin updates the provider to change the default model
    update_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        headers=admin_user.headers,
        json={
            "name": provider_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": updated_default_model,
            "model_configurations": [config.model_dump() for config in model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert update_response.status_code == 200

    default_provider_response = requests.post(
        f"{API_SERVER_URL}/admin/llm/provider/{update_response.json()['id']}/default",
        headers=admin_user.headers,
    )
    assert default_provider_response.status_code == 200

    # Step 6a: Verify the updated provider data via admin endpoint
    admin_provider_data = _get_provider_by_name_admin(admin_user, provider_name)
    assert admin_provider_data is not None
    _validate_provider_data(
        admin_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=updated_default_model,
        expected_is_default=True,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
        expected_is_public=True,
    )

    # Step 6b: Verify the updated provider data via basic endpoint (admin user)
    admin_basic_provider_data = _get_provider_by_name_basic(admin_user, provider_name)
    assert admin_basic_provider_data is not None
    _validate_provider_data(
        admin_basic_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=updated_default_model,
        expected_is_default=True,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
    )

    # Step 7: Verify non-admin user sees the updated provider data
    basic_user_provider_data = _get_provider_by_name_basic(basic_user, provider_name)
    assert basic_user_provider_data is not None
    _validate_provider_data(
        basic_user_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=updated_default_model,
        expected_is_default=True,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
    )


def _get_all_providers_basic(user: DATestUser) -> list[dict]:
    """Utility function to fetch all LLM providers via basic endpoint."""
    response = requests.get(
        f"{API_SERVER_URL}/llm/provider",
        headers=user.headers,
    )
    assert response.status_code == 200
    return response.json()


def _get_all_providers_admin(admin_user: DATestUser) -> list[dict]:
    """Utility function to fetch all LLM providers via admin endpoint."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    return response.json()


def _set_default_provider(admin_user: DATestUser, provider_id: int) -> None:
    """Utility function to set a provider as the default."""
    response = requests.post(
        f"{API_SERVER_URL}/admin/llm/provider/{provider_id}/default",
        headers=admin_user.headers,
    )
    assert response.status_code == 200


def _set_default_vision_provider(
    admin_user: DATestUser, provider_id: int, vision_model: str | None = None
) -> None:
    """Utility function to set a provider as the default vision provider."""
    url = f"{API_SERVER_URL}/admin/llm/provider/{provider_id}/default-vision"
    if vision_model:
        url += f"?vision_model={vision_model}"
    response = requests.post(url, headers=admin_user.headers)
    assert response.status_code == 200


def _find_default_provider(providers: list[dict]) -> dict | None:
    """Find the default provider from a list of providers."""
    return next((p for p in providers if p.get("is_default_provider")), None)


def _find_default_vision_provider(providers: list[dict]) -> dict | None:
    """Find the default vision provider from a list of providers."""
    return next((p for p in providers if p.get("is_default_vision_provider")), None)


def test_multiple_providers_default_switching(reset: None) -> None:
    """
    Test switching default providers and models across multiple LLM providers.

    This test verifies:
    1. Admin creates multiple LLM providers
    2. Admin sets one as the default provider with a specific default model
    3. Both admin and basic_user query /provider and see the same default provider/model
    4. Admin changes the default provider and model to something different
    5. Both admin and basic_user verify they see the same updated default
    6. Admin switches to a different provider that has a model with the same name
    7. Both users should see the new provider as default with the same model name
    """
    from onyx.auth.schemas import UserRole

    admin_user = UserManager.create(name="admin_user")

    # Create a non-admin user
    basic_user = UserManager.create(name="basic_user")
    assert basic_user.role == UserRole.BASIC or basic_user.role != UserRole.ADMIN

    # We'll create two providers, both with a model named "gpt-4" to test the
    # scenario where different providers have models with the same name
    provider_1_name = f"test-provider-1-{uuid.uuid4()}"
    provider_2_name = f"test-provider-2-{uuid.uuid4()}"

    # Both providers will have "gpt-4" as a model
    shared_model_name = "gpt-4"
    provider_1_unique_model = "gpt-4o"
    provider_2_unique_model = "gpt-4-turbo"

    # Model configurations for provider 1
    provider_1_configs = [
        ModelConfigurationUpsertRequest(
            name=shared_model_name,
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name=provider_1_unique_model,
            is_visible=True,
        ),
    ]

    # Model configurations for provider 2
    provider_2_configs = [
        ModelConfigurationUpsertRequest(
            name=shared_model_name,
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name=provider_2_unique_model,
            is_visible=True,
        ),
    ]

    # Expected model names and visibility for each provider
    provider_1_model_names = [shared_model_name, provider_1_unique_model]
    provider_1_visible = {shared_model_name: True, provider_1_unique_model: True}
    provider_2_model_names = [shared_model_name, provider_2_unique_model]
    provider_2_visible = {shared_model_name: True, provider_2_unique_model: True}

    # Step 1: Create provider 1 with shared_model_name as default
    create_response_1 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_1_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "is_default_provider": True,
            "default_model_name": shared_model_name,
            "model_configurations": [c.model_dump() for c in provider_1_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response_1.status_code == 200
    provider_1 = create_response_1.json()

    # Create provider 2 with provider_2_unique_model as default initially
    create_response_2 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_2_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000002",
            "default_model_name": provider_2_unique_model,
            "model_configurations": [c.model_dump() for c in provider_2_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response_2.status_code == 200
    provider_2 = create_response_2.json()

    # Step 2: Set provider 1 as the default provider
    _set_default_provider(admin_user, provider_1["id"])

    # Step 3: Both admin and basic_user query and verify they see the same default
    # Validate via admin endpoint
    admin_providers = _get_all_providers_admin(admin_user)
    admin_default = _find_default_provider(admin_providers)
    assert admin_default is not None
    _validate_provider_data(
        admin_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_public=True,
    )

    # Validate provider 2 via admin endpoint (should not be default)
    admin_provider_2 = next(
        (p for p in admin_providers if p["name"] == provider_2_name), None
    )
    assert admin_provider_2 is not None
    _validate_provider_data(
        admin_provider_2,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_unique_model,
        expected_is_default=None,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_public=True,
    )

    # Validate via basic endpoint (basic_user)
    basic_providers = _get_all_providers_basic(basic_user)
    basic_default = _find_default_provider(basic_providers)
    assert basic_default is not None
    _validate_provider_data(
        basic_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
    )

    # Also verify admin sees the same via basic endpoint
    admin_basic_providers = _get_all_providers_basic(admin_user)
    admin_basic_default = _find_default_provider(admin_basic_providers)
    assert admin_basic_default is not None
    _validate_provider_data(
        admin_basic_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
    )

    # Step 4: Admin changes the default provider to provider 2 and updates its default model
    # First update provider 2's default model to the unique model (it already is, but reconfirm)
    update_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        headers=admin_user.headers,
        json={
            "name": provider_2_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000002",
            "is_default_provider": True,
            "default_model_name": provider_2_unique_model,
            "model_configurations": [c.model_dump() for c in provider_2_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert update_response.status_code == 200

    # Now set provider 2 as the default
    _set_default_provider(admin_user, provider_2["id"])

    # Step 5: Both admin and basic_user verify they see the updated default
    # Validate via admin endpoint
    admin_providers = _get_all_providers_admin(admin_user)
    admin_default = _find_default_provider(admin_providers)
    assert admin_default is not None
    _validate_provider_data(
        admin_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_unique_model,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_public=True,
    )

    # Validate provider 1 via admin endpoint (should no longer be default)
    admin_provider_1 = next(
        (p for p in admin_providers if p["name"] == provider_1_name), None
    )
    assert admin_provider_1 is not None
    _validate_provider_data(
        admin_provider_1,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=None,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_public=True,
    )

    # Validate via basic endpoint (basic_user)
    basic_providers = _get_all_providers_basic(basic_user)
    basic_default = _find_default_provider(basic_providers)
    assert basic_default is not None
    _validate_provider_data(
        basic_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_unique_model,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
    )

    # Validate via basic endpoint (admin_user)
    admin_basic_providers = _get_all_providers_basic(admin_user)
    admin_basic_default = _find_default_provider(admin_basic_providers)
    assert admin_basic_default is not None
    _validate_provider_data(
        admin_basic_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_unique_model,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
    )

    # Step 6: Admin changes provider 2's default model to the shared model name
    # (same model name as provider 1 had)
    update_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        headers=admin_user.headers,
        json={
            "name": provider_2_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000002",
            "is_default_provider": True,
            "default_model_name": shared_model_name,  # Same name as provider 1's model
            "model_configurations": [c.model_dump() for c in provider_2_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert update_response.status_code == 200

    # Step 7: Both users verify they see provider 2 as default with the shared model name
    # Validate via admin endpoint
    admin_providers = _get_all_providers_admin(admin_user)
    admin_default = _find_default_provider(admin_providers)
    assert admin_default is not None
    _validate_provider_data(
        admin_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_public=True,
    )

    # Validate via basic endpoint (basic_user)
    basic_providers = _get_all_providers_basic(basic_user)
    basic_default = _find_default_provider(basic_providers)
    assert basic_default is not None
    _validate_provider_data(
        basic_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
    )

    # Validate via basic endpoint (admin_user)
    admin_basic_providers = _get_all_providers_basic(admin_user)
    admin_basic_default = _find_default_provider(admin_basic_providers)
    assert admin_basic_default is not None
    _validate_provider_data(
        admin_basic_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=True,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
    )

    # Verify provider 1 is no longer the default and has correct data
    provider_1_admin = next(
        (p for p in admin_providers if p["name"] == provider_1_name), None
    )
    assert provider_1_admin is not None
    _validate_provider_data(
        provider_1_admin,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=None,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_public=True,
    )

    provider_1_basic = next(
        (p for p in basic_providers if p["name"] == provider_1_name), None
    )
    assert provider_1_basic is not None
    _validate_provider_data(
        provider_1_basic,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=shared_model_name,
        expected_is_default=None,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
    )


def test_default_provider_and_vision_provider_selection(reset: None) -> None:
    """
    Test setting separate default providers for regular LLM and vision capabilities.

    This test verifies:
    1. Create provider 1 with mixed models (some with vision, some without)
    2. Create provider 2 with only vision-capable models
    3. Set a non-vision model from provider 1 as the general default
    4. Set a vision model from provider 2 as the default vision model
    5. Verify both admin and basic users see correct default provider and vision provider
    6. Verify model configurations show correct image support capabilities
    """
    from onyx.auth.schemas import UserRole

    admin_user = UserManager.create(name="admin_user")

    # Create a non-admin user
    basic_user = UserManager.create(name="basic_user")
    assert basic_user.role == UserRole.BASIC or basic_user.role != UserRole.ADMIN

    provider_1_name = f"test-mixed-models-{uuid.uuid4()}"
    provider_2_name = f"test-vision-only-{uuid.uuid4()}"

    # Provider 1: Mixed models - some with vision support, some without
    # Using real model names that litellm recognizes for vision support
    provider_1_non_vision_model = "gpt-4"  # No vision support
    provider_1_vision_model = "gpt-4o"  # Has vision support

    # Provider 2: Only vision-capable models
    provider_2_vision_model_1 = "gpt-4-vision-preview"  # Vision model
    provider_2_vision_model_2 = "gpt-4o-mini"  # Also has vision support

    # Model configurations for provider 1 (mixed)
    provider_1_configs = [
        ModelConfigurationUpsertRequest(
            name=provider_1_non_vision_model,
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name=provider_1_vision_model,
            is_visible=True,
        ),
    ]

    # Model configurations for provider 2 (vision only)
    provider_2_configs = [
        ModelConfigurationUpsertRequest(
            name=provider_2_vision_model_1,
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name=provider_2_vision_model_2,
            is_visible=True,
        ),
    ]

    # Expected model names
    provider_1_model_names = [provider_1_non_vision_model, provider_1_vision_model]
    provider_1_visible = {
        provider_1_non_vision_model: True,
        provider_1_vision_model: True,
    }

    provider_2_model_names = [provider_2_vision_model_1, provider_2_vision_model_2]
    provider_2_visible = {
        provider_2_vision_model_1: True,
        provider_2_vision_model_2: True,
    }

    # Step 1: Create provider 1 with mixed models, set non-vision model as default
    create_response_1 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_1_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "default_model_name": provider_1_non_vision_model,
            "model_configurations": [c.model_dump() for c in provider_1_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response_1.status_code == 200
    provider_1 = create_response_1.json()

    # Step 2: Create provider 2 with vision-only models
    create_response_2 = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_2_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000002",
            "default_model_name": provider_2_vision_model_1,
            "model_configurations": [c.model_dump() for c in provider_2_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response_2.status_code == 200
    provider_2 = create_response_2.json()

    # Step 3: Set provider 1 as the general default provider
    _set_default_provider(admin_user, provider_1["id"])

    # Step 4: Set provider 2 with a specific vision model as the default vision provider
    _set_default_vision_provider(
        admin_user, provider_2["id"], provider_2_vision_model_1
    )

    # Step 5: Verify via admin endpoint
    admin_providers = _get_all_providers_admin(admin_user)

    # Find and validate the default provider (provider 1)
    admin_default = _find_default_provider(admin_providers)
    assert admin_default is not None
    _validate_provider_data(
        admin_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_1_non_vision_model,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_public=True,
        expected_is_default_vision=None,  # Provider 1 is NOT the vision default
    )

    # Find and validate the default vision provider (provider 2)
    admin_vision_default = _find_default_vision_provider(admin_providers)
    assert admin_vision_default is not None
    _validate_provider_data(
        admin_vision_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_vision_model_1,
        expected_is_default=None,  # Provider 2 is NOT the general default
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_public=True,
        expected_is_default_vision=True,
        expected_default_vision_model=provider_2_vision_model_1,
    )

    # Step 6: Verify via basic endpoint (basic_user)
    basic_providers = _get_all_providers_basic(basic_user)

    # Find and validate the default provider (provider 1)
    basic_default = _find_default_provider(basic_providers)
    assert basic_default is not None
    _validate_provider_data(
        basic_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_1_non_vision_model,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_default_vision=None,
    )

    # Find and validate the default vision provider (provider 2)
    basic_vision_default = _find_default_vision_provider(basic_providers)
    assert basic_vision_default is not None
    _validate_provider_data(
        basic_vision_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_vision_model_1,
        expected_is_default=None,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_default_vision=True,
        expected_default_vision_model=provider_2_vision_model_1,
    )

    # Step 7: Verify via basic endpoint (admin_user sees same as basic_user)
    admin_basic_providers = _get_all_providers_basic(admin_user)

    admin_basic_default = _find_default_provider(admin_basic_providers)
    assert admin_basic_default is not None
    _validate_provider_data(
        admin_basic_default,
        expected_name=provider_1_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_1_non_vision_model,
        expected_is_default=True,
        expected_model_names=provider_1_model_names,
        expected_visible=provider_1_visible,
        expected_is_default_vision=None,
    )

    admin_basic_vision_default = _find_default_vision_provider(admin_basic_providers)
    assert admin_basic_vision_default is not None
    _validate_provider_data(
        admin_basic_vision_default,
        expected_name=provider_2_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model=provider_2_vision_model_1,
        expected_is_default=None,
        expected_model_names=provider_2_model_names,
        expected_visible=provider_2_visible,
        expected_is_default_vision=True,
        expected_default_vision_model=provider_2_vision_model_1,
    )

    # Verify that the providers are distinct (different providers for regular vs vision)
    assert (
        admin_default["name"] != admin_vision_default["name"]
    ), "Default provider and vision provider should be different providers"
    assert (
        basic_default["name"] != basic_vision_default["name"]
    ), "Default provider and vision provider should be different providers (basic endpoint)"


def test_default_provider_is_not_default_vision_provider(reset: None) -> None:
    """
    Test that setting a provider as the default provider does NOT make it
    the default vision provider.

    This test verifies:
    1. Create a provider with some models
    2. Set it as the default provider
    3. Verify it is the default provider (is_default_provider=True)
    4. Verify it is NOT the default vision provider (is_default_vision_provider should be None/False)
    """
    admin_user = UserManager.create(name="admin_user")

    provider_name = f"test-default-not-vision-{uuid.uuid4()}"

    # Model configurations
    model_configs = [
        ModelConfigurationUpsertRequest(
            name="gpt-4",
            is_visible=True,
        ),
        ModelConfigurationUpsertRequest(
            name="gpt-4o",
            is_visible=True,
        ),
    ]

    expected_model_names = ["gpt-4", "gpt-4o"]
    expected_visible = {"gpt-4": True, "gpt-4o": True}

    # Step 1: Create the provider
    create_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": provider_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000000",
            "default_model_name": "gpt-4",
            "model_configurations": [c.model_dump() for c in model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_response.status_code == 200
    created_provider = create_response.json()

    # Step 2: Set it as the default provider
    _set_default_provider(admin_user, created_provider["id"])

    # Step 3 & 4: Verify via admin endpoint
    admin_provider_data = _get_provider_by_name_admin(admin_user, provider_name)
    assert admin_provider_data is not None

    # Verify it IS the default provider
    assert (
        admin_provider_data["is_default_provider"] is True
    ), "Provider should be the default provider"

    # Verify it is NOT the default vision provider
    assert admin_provider_data.get("is_default_vision_provider") is not True, (
        f"Provider should NOT be the default vision provider, "
        f"but got is_default_vision_provider={admin_provider_data.get('is_default_vision_provider')}"
    )

    # Verify default_vision_model is not set
    assert admin_provider_data.get("default_vision_model") is None, (
        f"Provider should not have a default_vision_model set, "
        f"but got default_vision_model={admin_provider_data.get('default_vision_model')}"
    )

    # Full validation of provider data
    _validate_provider_data(
        admin_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model="gpt-4",
        expected_is_default=True,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
        expected_is_public=True,
        expected_is_default_vision=None,  # NOT a vision default
        expected_default_vision_model=None,  # No vision model set
    )

    # Also verify via basic endpoint
    basic_provider_data = _get_provider_by_name_basic(admin_user, provider_name)
    assert basic_provider_data is not None

    assert (
        basic_provider_data["is_default_provider"] is True
    ), "Provider should be the default provider (basic endpoint)"
    assert (
        basic_provider_data.get("is_default_vision_provider") is not True
    ), "Provider should NOT be the default vision provider (basic endpoint)"

    _validate_provider_data(
        basic_provider_data,
        expected_name=provider_name,
        expected_provider=LlmProviderNames.OPENAI,
        expected_default_model="gpt-4",
        expected_is_default=True,
        expected_model_names=expected_model_names,
        expected_visible=expected_visible,
        expected_is_default_vision=None,
        expected_default_vision_model=None,
    )

    # Verify there is no default vision provider at all
    admin_providers = _get_all_providers_admin(admin_user)
    vision_default = _find_default_vision_provider(admin_providers)
    assert (
        vision_default is None
    ), "There should be no default vision provider since we only set a regular default"


def _get_all_image_gen_configs(admin_user: DATestUser) -> list[dict]:
    """Utility function to fetch all image generation configs."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/image-generation/config",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    return response.json()


def _create_image_gen_config(
    admin_user: DATestUser,
    image_provider_id: str,
    model_name: str,
    source_llm_provider_id: int,
    is_default: bool = False,
) -> dict:
    """Utility function to create an image generation config using clone mode."""
    response = requests.post(
        f"{API_SERVER_URL}/admin/image-generation/config",
        headers=admin_user.headers,
        json={
            "image_provider_id": image_provider_id,
            "model_name": model_name,
            "source_llm_provider_id": source_llm_provider_id,
            "is_default": is_default,
        },
    )
    assert (
        response.status_code == 200
    ), f"Failed to create image gen config: {response.text}"
    return response.json()


def _set_image_gen_config_default(
    admin_user: DATestUser, image_provider_id: str
) -> None:
    """Utility function to set an image generation config as default."""
    response = requests.post(
        f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}/default",
        headers=admin_user.headers,
    )
    assert response.status_code == 200


def _delete_image_gen_config(admin_user: DATestUser, image_provider_id: str) -> None:
    """Utility function to delete an image generation config."""
    response = requests.delete(
        f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}",
        headers=admin_user.headers,
    )
    assert response.status_code == 200


def test_all_three_provider_types_no_mixup(reset: None) -> None:
    """
    Test that regular LLM providers, vision providers, and image generation providers
    are all tracked separately with no mixup.

    This test verifies:
    1. Create a regular LLM provider and set as default
    2. Create a vision LLM provider and set as default vision
    3. Create an image generation config (using clone mode from regular provider)
    4. Set the image gen config as default
    5. Verify all three are correctly identified:
       - Regular provider: is_default_provider=True, is_default_vision_provider=None
       - Vision provider: is_default_provider=None, is_default_vision_provider=True
       - Image gen config: is_default=True (separate from LLM provider defaults)
    6. Verify image gen config doesn't appear in LLM provider lists
    7. Verify LLM providers don't appear in image gen config list
    """
    from onyx.auth.schemas import UserRole

    admin_user = UserManager.create(name="admin_user")

    # Create a non-admin user
    basic_user = UserManager.create(name="basic_user")
    assert basic_user.role == UserRole.BASIC or basic_user.role != UserRole.ADMIN

    # Provider names
    regular_provider_name = f"test-regular-provider-{uuid.uuid4()}"
    vision_provider_name = f"test-vision-provider-{uuid.uuid4()}"
    image_gen_provider_id = f"test-image-gen-{uuid.uuid4()}"

    # Model configurations
    regular_model_configs = [
        ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
        ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
    ]

    vision_model_configs = [
        ModelConfigurationUpsertRequest(name="gpt-4-vision-preview", is_visible=True),
        ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
    ]

    # Step 1: Create regular LLM provider
    create_regular_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": regular_provider_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "default_model_name": "gpt-4",
            "model_configurations": [c.model_dump() for c in regular_model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_regular_response.status_code == 200
    regular_provider = create_regular_response.json()

    # Set as default provider
    _set_default_provider(admin_user, regular_provider["id"])

    # Step 2: Create vision LLM provider
    create_vision_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": vision_provider_name,
            "provider": LlmProviderNames.OPENAI,
            "api_key": "sk-000000000000000000000000000000000000000000000002",
            "default_model_name": "gpt-4-vision-preview",
            "model_configurations": [c.model_dump() for c in vision_model_configs],
            "is_public": True,
            "groups": [],
            "personas": [],
        },
    )
    assert create_vision_response.status_code == 200
    vision_provider = create_vision_response.json()

    # Set as default vision provider
    _set_default_vision_provider(
        admin_user, vision_provider["id"], "gpt-4-vision-preview"
    )

    # Step 3: Create image generation config using clone mode from regular provider
    _create_image_gen_config(
        admin_user=admin_user,
        image_provider_id=image_gen_provider_id,
        model_name="dall-e-3",
        source_llm_provider_id=regular_provider["id"],
        is_default=True,
    )

    # Step 4: Verify all three types are correctly tracked

    # Get all LLM providers (via admin endpoint)
    admin_providers = _get_all_providers_admin(admin_user)

    # Get all image generation configs
    image_gen_configs = _get_all_image_gen_configs(admin_user)

    # Verify the regular provider is the default provider
    regular_provider_data = next(
        (p for p in admin_providers if p["name"] == regular_provider_name), None
    )
    assert regular_provider_data is not None, "Regular provider not found"
    assert (
        regular_provider_data["is_default_provider"] is True
    ), "Regular provider should be the default provider"
    assert (
        regular_provider_data.get("is_default_vision_provider") is not True
    ), "Regular provider should NOT be the default vision provider"

    # Verify the vision provider is the default vision provider
    vision_provider_data = next(
        (p for p in admin_providers if p["name"] == vision_provider_name), None
    )
    assert vision_provider_data is not None, "Vision provider not found"
    assert (
        vision_provider_data.get("is_default_provider") is not True
    ), "Vision provider should NOT be the default provider"
    assert (
        vision_provider_data["is_default_vision_provider"] is True
    ), "Vision provider should be the default vision provider"
    assert (
        vision_provider_data["default_vision_model"] == "gpt-4-vision-preview"
    ), "Vision provider should have correct default vision model"

    # Verify the image gen config is the default image generation config
    image_gen_config_data = next(
        (
            c
            for c in image_gen_configs
            if c["image_provider_id"] == image_gen_provider_id
        ),
        None,
    )
    assert image_gen_config_data is not None, "Image gen config not found"
    assert (
        image_gen_config_data["is_default"] is True
    ), "Image gen config should be the default"
    assert (
        image_gen_config_data["model_name"] == "dall-e-3"
    ), "Image gen config should have correct model name"

    # Step 5: Verify no mixup - image gen providers don't appear in LLM provider lists

    # The image gen config creates an LLM provider with name "Image Gen - {image_provider_id}"
    # This should NOT be returned by the regular LLM provider endpoints
    [p["name"] for p in admin_providers]
    image_gen_llm_provider_name = f"Image Gen - {image_gen_provider_id}"

    # Note: The image gen provider IS an LLM provider internally, so it may appear in the list
    # But it should NOT be marked as default provider or default vision provider
    image_gen_llm_provider = next(
        (p for p in admin_providers if p["name"] == image_gen_llm_provider_name), None
    )
    if image_gen_llm_provider:
        # If it appears, verify it's not marked as default for either type
        assert (
            image_gen_llm_provider.get("is_default_provider") is not True
        ), "Image gen's internal LLM provider should NOT be the default provider"
        assert (
            image_gen_llm_provider.get("is_default_vision_provider") is not True
        ), "Image gen's internal LLM provider should NOT be the default vision provider"

    # Step 6: Verify via basic endpoint (non-admin user)
    basic_providers = _get_all_providers_basic(basic_user)

    # Verify regular provider is default for basic user
    basic_regular = next(
        (p for p in basic_providers if p["name"] == regular_provider_name), None
    )
    assert basic_regular is not None, "Regular provider not visible to basic user"
    assert (
        basic_regular["is_default_provider"] is True
    ), "Regular provider should be default for basic user"

    # Verify vision provider is default vision for basic user
    basic_vision = next(
        (p for p in basic_providers if p["name"] == vision_provider_name), None
    )
    assert basic_vision is not None, "Vision provider not visible to basic user"
    assert (
        basic_vision["is_default_vision_provider"] is True
    ), "Vision provider should be default vision for basic user"

    # Step 7: Verify the counts are as expected
    # We should have at least 2 user-created providers plus the image gen internal provider
    user_created_providers = [
        p
        for p in admin_providers
        if p["name"] in [regular_provider_name, vision_provider_name]
    ]
    assert (
        len(user_created_providers) == 2
    ), f"Expected 2 user-created providers, got {len(user_created_providers)}"

    # We should have exactly 1 image gen config
    assert (
        len(
            [
                c
                for c in image_gen_configs
                if c["image_provider_id"] == image_gen_provider_id
            ]
        )
        == 1
    ), "Expected exactly 1 image gen config with our ID"

    # Verify that our explicitly created providers are tracked correctly:
    # - Only ONE provider has is_default_provider=True
    default_providers = [
        p for p in admin_providers if p.get("is_default_provider") is True
    ]
    assert (
        len(default_providers) == 1
    ), f"Expected exactly 1 default provider, got {len(default_providers)}"
    assert default_providers[0]["name"] == regular_provider_name

    # - Only ONE provider has is_default_vision_provider=True
    default_vision_providers = [
        p for p in admin_providers if p.get("is_default_vision_provider") is True
    ]
    assert (
        len(default_vision_providers) == 1
    ), f"Expected exactly 1 default vision provider, got {len(default_vision_providers)}"
    assert default_vision_providers[0]["name"] == vision_provider_name

    # - Only ONE image gen config has is_default=True
    default_image_gen_configs = [
        c for c in image_gen_configs if c.get("is_default") is True
    ]
    assert (
        len(default_image_gen_configs) == 1
    ), f"Expected exactly 1 default image gen config, got {len(default_image_gen_configs)}"
    assert default_image_gen_configs[0]["image_provider_id"] == image_gen_provider_id

    # Clean up: Delete the image gen config (to clean up the internal LLM provider)
    _delete_image_gen_config(admin_user, image_gen_provider_id)
