from onyx.db.models import OAuthAccount
from onyx.db.oauth_accounts import select_live_oauth_token

_CONFIGURED: set[str] = {"openid"}


def _link(
    account_id: str, expires_at: int | None, oauth_name: str = "openid"
) -> OAuthAccount:
    return OAuthAccount(
        oauth_name=oauth_name,
        access_token=f"token-{account_id}",
        refresh_token="",
        account_id=account_id,
        account_email="user@example.com",
        expires_at=expires_at,
    )


def test_no_links_returns_none() -> None:
    assert select_live_oauth_token([], _CONFIGURED) is None


def test_picks_latest_expiry_over_row_order() -> None:
    stale: OAuthAccount = _link("old-subject", expires_at=1_000)
    live: OAuthAccount = _link("new-subject", expires_at=2_000)
    assert select_live_oauth_token([stale, live], _CONFIGURED) == "token-new-subject"


def test_link_without_expiry_loses_to_a_dated_one() -> None:
    undated: OAuthAccount = _link("undated", expires_at=None)
    dated: OAuthAccount = _link("dated", expires_at=1)
    assert select_live_oauth_token([undated, dated], _CONFIGURED) == "token-dated"


def test_all_undated_keeps_first_row() -> None:
    first: OAuthAccount = _link("first", expires_at=None)
    second: OAuthAccount = _link("second", expires_at=None)
    assert select_live_oauth_token([first, second], _CONFIGURED) == "token-first"


def test_unconfigured_provider_never_wins() -> None:
    retired: OAuthAccount = _link("google-subject", 9_000, oauth_name="google")
    live: OAuthAccount = _link("new-subject", expires_at=2_000)
    assert select_live_oauth_token([retired, live], _CONFIGURED) == "token-new-subject"


def test_only_unconfigured_links_returns_none() -> None:
    retired: OAuthAccount = _link("google-subject", 9_000, oauth_name="google")
    assert select_live_oauth_token([retired], _CONFIGURED) is None
