from unittest.mock import MagicMock, patch

from ee.onyx.server.enterprise_settings.store import load_settings, store_settings


def test_legacy_hide_onyx_branding_is_dropped_on_load_and_save() -> None:
    kv_store = MagicMock()
    kv_store.load.return_value = {
        "application_name": "Acme",
        "hide_onyx_branding": True,
    }

    with patch(
        "ee.onyx.server.enterprise_settings.store.get_kv_store",
        return_value=kv_store,
    ):
        settings = load_settings()
        store_settings(settings)

    assert settings.application_name == "Acme"
    assert "hide_onyx_branding" not in settings.model_dump()
    stored = kv_store.store.call_args.args[1]
    assert "hide_onyx_branding" not in stored
    assert stored["application_name"] == "Acme"
