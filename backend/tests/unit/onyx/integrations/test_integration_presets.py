from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.integrations.presets import PRESETS, get_preset
from onyx.skills.built_in import BUILT_IN_SKILLS, EXTERNAL_APP_BUILT_IN_SKILL_IDS

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


def test_presets_match_their_providers_and_built_in_skills() -> None:
    for app_type, preset in PRESETS.items():
        assert preset.id == app_type.value
        assert preset.app_type is app_type
        assert preset.provider is PROVIDERS[app_type]
        assert preset.name == preset.provider.spec.app_name
        assert preset.built_in_skill_id == EXTERNAL_APP_BUILT_IN_SKILL_IDS[app_type]
        assert preset.built_in_skill_id in BUILT_IN_SKILLS
