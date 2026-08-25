from onyx.db.enums import SupportedLanguage


def test_supported_language_values_match_frontend_locales() -> None:
    """Pin the enum values that the frontend locale registry mirrors.

    web/src/i18n/config.ts keeps a copy of this list (SUPPORTED_LOCALES).
    If this test fails, update both places together.
    """
    assert [language.value for language in SupportedLanguage] == [
        "en",
        "es",
        "pt",
        "fr",
        "de",
    ]
