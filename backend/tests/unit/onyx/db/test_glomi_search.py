from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.glomi_search import GlomiDefaultWebSearchConfig
from onyx.db.glomi_search import seed_glomi_default_web_search_provider
from shared_configs.enums import WebSearchProviderType


def _config(
    *,
    enabled: bool = True,
    api_base: str | None = "https://search.example.test",
    api_key: str | None = "gateway-key",
    channel: str | None = "tavily",
) -> GlomiDefaultWebSearchConfig:
    return GlomiDefaultWebSearchConfig(
        enabled=enabled,
        api_base=api_base,
        api_key=api_key,
        channel=channel,
    )


def _provider(
    *,
    provider_id: int = 7,
    provider_type: str = "glomi",
    is_active: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=provider_id,
        provider_type=provider_type,
        is_active=is_active,
    )


def test_seed_skips_when_disabled() -> None:
    result = seed_glomi_default_web_search_provider(Mock(), _config(enabled=False))

    assert result.seeded is False
    assert result.reason == "disabled"


def test_seed_skips_when_api_base_missing() -> None:
    result = seed_glomi_default_web_search_provider(Mock(), _config(api_base=""))

    assert result.seeded is False
    assert result.reason == "missing_api_base"


def test_seed_skips_when_api_key_missing() -> None:
    result = seed_glomi_default_web_search_provider(Mock(), _config(api_key=None))

    assert result.seeded is False
    assert result.reason == "missing_api_key"


def test_seed_creates_and_activates_when_no_active_provider(monkeypatch) -> None:
    upsert_web_search_provider = Mock(return_value=_provider(is_active=True))

    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_web_search_provider_by_name_and_type",
        Mock(return_value=None),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_active_web_search_provider",
        Mock(return_value=None),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.upsert_web_search_provider", upsert_web_search_provider
    )

    db_session = Mock()
    result = seed_glomi_default_web_search_provider(db_session, _config())

    assert result.seeded is True
    assert result.reason == "seeded"
    upsert_web_search_provider.assert_called_once()
    kwargs = upsert_web_search_provider.call_args.kwargs
    assert kwargs["provider_id"] is None
    assert kwargs["name"] == "Glomi Search"
    assert kwargs["provider_type"] == WebSearchProviderType.GLOMI
    assert kwargs["api_key"] == "gateway-key"
    assert kwargs["api_key_changed"] is True
    assert kwargs["config"] == {
        "base_url": "https://search.example.test",
        "channel": "tavily",
    }
    assert kwargs["activate"] is True
    assert kwargs["db_session"] is db_session


def test_seed_updates_existing_glomi_provider(monkeypatch) -> None:
    existing = _provider(provider_id=11, provider_type="glomi", is_active=True)
    upsert_web_search_provider = Mock(return_value=existing)

    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_web_search_provider_by_name_and_type",
        Mock(return_value=existing),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_active_web_search_provider",
        Mock(return_value=existing),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.upsert_web_search_provider", upsert_web_search_provider
    )

    seed_glomi_default_web_search_provider(
        Mock(), _config(api_base="https://new.example.test", channel=None)
    )

    kwargs = upsert_web_search_provider.call_args.kwargs
    assert kwargs["provider_id"] == 11
    assert kwargs["config"] == {"base_url": "https://new.example.test"}
    assert kwargs["activate"] is True


def test_seed_does_not_override_active_non_glomi_provider(monkeypatch) -> None:
    existing_glomi = _provider(provider_id=11, provider_type="glomi")
    active_admin_provider = _provider(provider_id=22, provider_type="brave", is_active=True)
    upsert_web_search_provider = Mock(return_value=existing_glomi)

    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_web_search_provider_by_name_and_type",
        Mock(return_value=existing_glomi),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.fetch_active_web_search_provider",
        Mock(return_value=active_admin_provider),
    )
    monkeypatch.setattr(
        "onyx.db.glomi_search.upsert_web_search_provider", upsert_web_search_provider
    )

    seed_glomi_default_web_search_provider(Mock(), _config())

    assert upsert_web_search_provider.call_args.kwargs["activate"] is False
