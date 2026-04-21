"""Unit tests for the OAuth reCAPTCHA cookie helpers in onyx.auth.captcha."""

from onyx.auth import captcha as captcha_module


def test_issued_cookie_validates() -> None:
    """A freshly issued cookie passes validation."""
    cookie = captcha_module.issue_captcha_cookie_value()
    assert captcha_module.validate_captcha_cookie_value(cookie) is True


def test_validate_rejects_none() -> None:
    assert captcha_module.validate_captcha_cookie_value(None) is False


def test_validate_rejects_empty_string() -> None:
    assert captcha_module.validate_captcha_cookie_value("") is False


def test_validate_rejects_malformed_no_separator() -> None:
    assert captcha_module.validate_captcha_cookie_value("nodot") is False


def test_validate_rejects_non_numeric_expiry() -> None:
    assert captcha_module.validate_captcha_cookie_value("notanumber.deadbeef") is False


def test_validate_rejects_tampered_signature() -> None:
    """Swapping the signature while keeping the expiry is rejected."""
    cookie = captcha_module.issue_captcha_cookie_value()
    expiry, _sig = cookie.split(".", 1)
    tampered = f"{expiry}.deadbeefdeadbeefdeadbeefdeadbeef"
    assert captcha_module.validate_captcha_cookie_value(tampered) is False


def test_validate_rejects_expired_timestamp() -> None:
    """An expiry in the past is rejected even with a valid signature."""
    cookie = captcha_module.issue_captcha_cookie_value(now=0)
    assert captcha_module.validate_captcha_cookie_value(cookie) is False


def test_validate_rejects_modified_expiry() -> None:
    """Bumping the expiry forward invalidates the signature."""
    cookie = captcha_module.issue_captcha_cookie_value()
    _expiry, sig = cookie.split(".", 1)
    bumped = f"99999999999.{sig}"
    assert captcha_module.validate_captcha_cookie_value(bumped) is False
