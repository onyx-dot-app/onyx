from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.integrations.presets import PRESETS, get_preset

BUILT_IN_PROVIDER_NAMES = {
    "Slack",
    "Google Calendar",
    "Google Drive",
    "Gmail",
    "Linear",
    "GitHub",
    "HubSpot",
    "Notion",
    "Zendesk",
}


def test_each_built_in_provider_is_a_preset() -> None:
    assert set(PRESETS) == set(ExternalAppType) - {ExternalAppType.CUSTOM}
    assert set(PRESETS) == set(PROVIDERS)
    assert {preset.name for preset in PRESETS.values()} == BUILT_IN_PROVIDER_NAMES
    assert get_preset(ExternalAppType.CUSTOM) is None


def test_presets_match_their_providers() -> None:
    for app_type, preset in PRESETS.items():
        assert preset.id == app_type.value
        assert preset.app_type is app_type
        assert preset.provider is PROVIDERS[app_type]
        assert preset.name == preset.provider.spec.app_name
