from onyx.llm.constants import LlmProviderNames
from onyx.llm.custom_config_mapping import get_unsupported_custom_config_keys
from onyx.llm.custom_config_mapping import map_custom_config_to_model_kwargs


def test_bedrock_env_format_keys_map_to_kwargs() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.BEDROCK,
        custom_config={
            "AWS_ACCESS_KEY_ID": "akid",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_SESSION_TOKEN": "session",
            "AWS_REGION_NAME": "us-east-1",
        },
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {
        "aws_access_key_id": "akid",
        "aws_secret_access_key": "secret",
        "aws_session_token": "session",
        "aws_region_name": "us-east-1",
    }
    assert mapping.consumed_keys == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION_NAME",
    }


def test_bedrock_bearer_token_maps_to_api_key() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.BEDROCK,
        custom_config={"AWS_BEARER_TOKEN_BEDROCK": "bearer"},
        api_key="stored-key",
        api_base=None,
    )
    # Provider-specific keys keep clobber semantics: the kwarg is produced
    # even though a provider-level api_key exists.
    assert mapping.model_kwargs == {"api_key": "bearer"}


def test_bedrock_converse_uses_bedrock_mapping() -> None:
    """Converse shares Bedrock's mapping: LiteLLM's BaseAWSLLM backs both paths
    and treats api_key as the bearer token."""
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.BEDROCK_CONVERSE,
        custom_config={
            "AWS_REGION_NAME": "eu-west-1",
            "AWS_BEARER_TOKEN_BEDROCK": "bearer",
        },
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {
        "aws_region_name": "eu-west-1",
        "api_key": "bearer",
    }


def test_vertex_api_key_stays_env_only() -> None:
    """Vertex auths via credentials, never a bare API key: a VERTEX_AI_API_KEY
    entry must not be consumed by the generic <PROVIDER>_API_KEY matcher."""
    custom_config = {"VERTEX_AI_API_KEY": "key"}
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.VERTEX_AI,
        custom_config=custom_config,
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {}
    assert mapping.consumed_keys == frozenset()
    assert get_unsupported_custom_config_keys(
        LlmProviderNames.VERTEX_AI, custom_config
    ) == {"VERTEX_AI_API_KEY"}


def test_vertex_service_account_maps_credentials() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.VERTEX_AI,
        custom_config={
            "vertex_auth_method": "service_account_json",
            "vertex_credentials": "{}",
            "vertex_location": "global",
            "vertex_project": "proj",
        },
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {
        "vertex_credentials": "{}",
        "vertex_location": "global",
        "vertex_project": "proj",
    }
    assert "vertex_auth_method" in mapping.consumed_keys


def test_vertex_workload_identity_omits_credentials() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.VERTEX_AI,
        custom_config={
            "vertex_auth_method": "workload_identity",
            "vertex_credentials": "{}",
            "CREDENTIALS_FILE": "{}",
            "vertex_project": "proj",
        },
        api_key=None,
        api_base=None,
    )
    assert "vertex_credentials" not in mapping.model_kwargs
    assert mapping.model_kwargs == {"vertex_project": "proj"}
    # Still consumed: the keys must never fall through to env injection.
    assert "vertex_credentials" in mapping.consumed_keys
    assert "CREDENTIALS_FILE" in mapping.consumed_keys


def test_azure_ad_token_maps_to_kwarg() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider=LlmProviderNames.AZURE,
        custom_config={"AZURE_AD_TOKEN": "ad-token"},
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {"azure_ad_token": "ad-token"}


def test_generic_provider_api_key_applied_when_unset() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider="groq",
        custom_config={"GROQ_API_KEY": "gk"},
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {"api_key": "gk"}
    assert mapping.consumed_keys == {"GROQ_API_KEY"}


def test_generic_provider_api_key_ignored_when_explicit_key_set() -> None:
    # Mirrors LiteLLM's param-over-env precedence: the key is recognized
    # (never env-injected) but the explicit api_key wins.
    mapping = map_custom_config_to_model_kwargs(
        model_provider="groq",
        custom_config={"GROQ_API_KEY": "gk"},
        api_key="explicit",
        api_base=None,
    )
    assert mapping.model_kwargs == {}
    assert mapping.consumed_keys == {"GROQ_API_KEY"}


def test_generic_provider_api_base_normalized_match() -> None:
    mapping = map_custom_config_to_model_kwargs(
        model_provider="together_ai",
        custom_config={"TOGETHERAI_API_BASE": "https://api.together.xyz"},
        api_key=None,
        api_base=None,
    )
    assert mapping.model_kwargs == {"api_base": "https://api.together.xyz"}


def test_unsupported_keys_reported() -> None:
    unsupported = get_unsupported_custom_config_keys(
        "cloudflare",
        {
            "CLOUDFLARE_ACCOUNT_ID": "acct",
            "CLOUDFLARE_API_KEY": "ck",
        },
    )
    assert unsupported == {"CLOUDFLARE_ACCOUNT_ID"}


def test_empty_config_has_no_unsupported_keys() -> None:
    assert get_unsupported_custom_config_keys("openai", None) == set()
    assert get_unsupported_custom_config_keys("openai", {}) == set()
