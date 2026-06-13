from onyx.llm.consumer_model_catalog import DEFAULT_CONSUMER_MODEL_PROFILE_ID
from onyx.llm.consumer_model_catalog import get_consumer_model_catalog_response
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
from onyx.llm.consumer_model_catalog import get_default_consumer_model_profile
from onyx.llm.consumer_model_catalog import profile_to_llm_override
from onyx.llm.consumer_model_catalog import profile_to_user_default_model
from onyx.llm.consumer_model_catalog import resolve_consumer_model_profile_id
from onyx.llm.consumer_model_catalog import resolve_profile_id_from_user_default_model
from onyx.llm.consumer_model_catalog import resolve_single_model_profile_id


def test_default_consumer_profile_is_balanced() -> None:
    default_profile = get_default_consumer_model_profile()

    assert DEFAULT_CONSUMER_MODEL_PROFILE_ID == "balanced"
    assert default_profile.id == "balanced"
    assert default_profile.model_name == "qwen-plus"


def test_unknown_consumer_profile_falls_back_to_default() -> None:
    assert resolve_consumer_model_profile_id("not-a-profile") == "balanced"
    assert resolve_consumer_model_profile_id(None) == "balanced"


def test_catalog_response_contains_only_safe_profile_fields() -> None:
    response = get_consumer_model_catalog_response()
    first_profile = response.profiles[0]
    serialized = first_profile.model_dump()

    assert response.default_profile_id == "balanced"
    assert "api_key" not in serialized
    assert "api_base" not in serialized
    assert "provider_id" not in serialized
    assert "temperature" not in serialized
    assert {"id", "label", "description", "supports_image"}.issubset(serialized)


def test_profile_to_user_default_model_uses_existing_structured_format() -> None:
    profile = get_consumer_model_profile("coding")

    assert profile_to_user_default_model(profile) == (
        "Qwen Coder__openai_compatible__qwen3-coder-plus"
    )


def test_resolve_profile_from_user_default_model_falls_back_for_stale_value() -> None:
    assert (
        resolve_profile_id_from_user_default_model(
            "Qwen Coder__openai_compatible__qwen3-coder-plus"
        )
        == "coding"
    )
    assert resolve_profile_id_from_user_default_model("stale-model") == "balanced"


def test_profile_to_llm_override_uses_provider_name_for_backend_resolution() -> None:
    override = profile_to_llm_override(get_consumer_model_profile("fast"))

    assert override.model_provider == "Qwen"
    assert override.model_version == "qwen-turbo"
    assert override.temperature == 0.7
    assert override.display_name == "Qwen Turbo"


def test_single_model_profile_resolution_prefers_deep_research_scene() -> None:
    assert (
        resolve_single_model_profile_id(
            user_default_model=(
                "Qwen Coder__openai_compatible__qwen3-coder-plus"
            ),
            is_deep_research=True,
        )
        == "deep"
    )


def test_single_model_profile_resolution_uses_user_preference_for_chat() -> None:
    assert (
        resolve_single_model_profile_id(
            user_default_model=(
                "Qwen Coder__openai_compatible__qwen3-coder-plus"
            ),
            is_deep_research=False,
        )
        == "coding"
    )
