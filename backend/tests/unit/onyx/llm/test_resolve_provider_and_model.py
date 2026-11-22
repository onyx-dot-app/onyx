"""An override's model_configuration_id must beat name-based resolution —
provider display names are not unique, so only the id routes unambiguously."""

from unittest.mock import MagicMock, patch

from onyx.llm.factory import _resolve_provider_and_model

_FETCH_MC = "onyx.llm.factory.fetch_model_configuration_by_id"
_FETCH_PROVIDER = "onyx.llm.factory.fetch_existing_llm_provider"
_FETCH_MC_BY_NAME = "onyx.llm.factory.fetch_model_configuration_by_provider_id_and_name"


def _mc(name: str, provider: MagicMock) -> MagicMock:
    mc = MagicMock()
    mc.name = name
    mc.llm_provider = provider
    return mc


def test_model_configuration_id_beats_name_resolution() -> None:
    responses_provider = MagicMock()
    mc = _mc("gateway/gpt-model", responses_provider)

    with (
        patch(_FETCH_MC, return_value=mc) as fetch_mc,
        patch(_FETCH_PROVIDER) as fetch_provider,
    ):
        resolved = _resolve_provider_and_model(
            persona=MagicMock(),
            provider_name_override="Gateway Dual",
            model_version_override="gateway/gpt-model",
            db_session=MagicMock(),
            model_configuration_override_id=202,
        )

    assert resolved == (responses_provider, "gateway/gpt-model", mc)
    fetch_mc.assert_called_once()
    fetch_provider.assert_not_called()


def test_stale_model_configuration_id_falls_back_to_default_not_name() -> None:
    # A deleted configuration must not reroute through a possibly same-named
    # provider; None sends the caller to the default LLM.
    with (
        patch(_FETCH_MC, return_value=None),
        patch(_FETCH_PROVIDER) as fetch_provider,
    ):
        resolved = _resolve_provider_and_model(
            persona=MagicMock(),
            provider_name_override="Gateway Dual",
            model_version_override="gateway/gpt-model",
            db_session=MagicMock(),
            model_configuration_override_id=999,
        )

    assert resolved is None
    fetch_provider.assert_not_called()


def test_no_id_uses_name_resolution_unchanged() -> None:
    name_provider = MagicMock()
    mc = _mc("gateway/gpt-model", name_provider)

    with (
        patch(_FETCH_MC) as fetch_mc,
        patch(_FETCH_PROVIDER, return_value=name_provider),
        patch(_FETCH_MC_BY_NAME, return_value=mc) as fetch_mc_by_name,
    ):
        resolved = _resolve_provider_and_model(
            persona=MagicMock(),
            provider_name_override="Gateway Dual",
            model_version_override="gateway/gpt-model",
            db_session=MagicMock(),
        )

    assert resolved == (name_provider, "gateway/gpt-model", mc)
    fetch_mc.assert_not_called()
    assert fetch_mc_by_name.call_args.args[1:] == (
        name_provider.id,
        "gateway/gpt-model",
    )
