"""mask_credential_dict must pass whitelisted keys through whole (any value
type) while non-whitelisted strings and lists stay masked, so non-secret
lists like OAuth scopes survive an admin-UI round trip."""

from onyx.utils.encryption import mask_credential_dict


def test_whitelisted_list_passes_through_unmasked() -> None:
    masked = mask_credential_dict(
        {"scopes": ["openid", "email"], "client_secret": "supersecretvalue"}
    )
    assert masked["scopes"] == ["openid", "email"]
    assert masked["client_secret"] != "supersecretvalue"


def test_non_whitelisted_list_items_still_mask() -> None:
    masked = mask_credential_dict({"recovery_codes": ["alpha", "beta"]})
    assert masked["recovery_codes"] != ["alpha", "beta"]


def test_whitelisted_string_passes_through() -> None:
    masked = mask_credential_dict({"wiki_base": "https://wiki.example.com"})
    assert masked["wiki_base"] == "https://wiki.example.com"
