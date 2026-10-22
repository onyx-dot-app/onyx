from onyx.db.models import OAuthAccount, User


def _link(account_id: str, expires_at: int | None) -> OAuthAccount:
    return OAuthAccount(
        oauth_name="openid",
        access_token=f"token-{account_id}",
        refresh_token="",
        account_id=account_id,
        account_email="user@example.com",
        expires_at=expires_at,
    )


def test_no_links_returns_none() -> None:
    assert User(oauth_accounts=[]).live_oauth_token is None


def test_picks_latest_expiry_over_row_order() -> None:
    stale = _link("old-subject", expires_at=1_000)
    live = _link("new-subject", expires_at=2_000)
    user = User(oauth_accounts=[stale, live])
    assert user.live_oauth_token == "token-new-subject"


def test_link_without_expiry_loses_to_a_dated_one() -> None:
    undated = _link("undated", expires_at=None)
    dated = _link("dated", expires_at=1)
    user = User(oauth_accounts=[undated, dated])
    assert user.live_oauth_token == "token-dated"


def test_all_undated_keeps_first_row() -> None:
    first = _link("first", expires_at=None)
    second = _link("second", expires_at=None)
    user = User(oauth_accounts=[first, second])
    assert user.live_oauth_token == "token-first"
