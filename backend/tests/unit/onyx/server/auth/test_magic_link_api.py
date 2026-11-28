"""The magic link routes: what is refused before an email goes out, what the
email carries, what a click gets back, and the playground's two extra rules."""

import hashlib
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from onyx.auth import magic_link
from onyx.auth.magic_link import (
    MAGIC_LINK_BROWSER_COOKIE,
    MAGIC_LINK_WRONG_EMAIL_CODE,
    MagicLinkRecord,
)
from onyx.auth.users import auth_backend, get_user_manager
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.server.auth import magic_link_api
from onyx.server.auth.magic_link_api import (
    MAGIC_LINK_INVALID_CODE,
    MAGIC_LINK_USE_SSO_CODE,
    router,
)
from onyx.utils.variable_functionality import global_version

_MODULE = "onyx.server.auth.magic_link_api"
EMAIL = "Someone@Example.com"


@pytest.fixture
def user_manager() -> MagicMock:
    manager = MagicMock()
    manager.magic_link_login = AsyncMock()
    manager.on_after_login = AsyncMock()
    return manager


@pytest.fixture
def client(user_manager: MagicMock) -> TestClient:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_user_manager] = lambda: user_manager
    app.dependency_overrides[auth_backend.get_strategy] = lambda: object()
    return TestClient(app)


@pytest.fixture
def mail_is_configured() -> Iterator[None]:
    with patch(f"{_MODULE}.EMAIL_CONFIGURED", True):
        yield


@pytest.fixture
def address_passes() -> Iterator[dict[str, MagicMock]]:
    """A work address: the domain checks pass and the store and sender are
    stand-ins."""
    settings = MagicMock()
    settings.valid_email_domains = ()
    with (
        patch(f"{_MODULE}.is_sso_only", return_value=False),
        patch(f"{_MODULE}.get_security_settings", return_value=settings),
        patch(f"{_MODULE}.verify_email_domain") as verify_domain,
        patch(f"{_MODULE}.reserve_send", AsyncMock(return_value="claim")) as reserve,
        patch(f"{_MODULE}.release_send", AsyncMock()) as release,
        patch(f"{_MODULE}.store_magic_link", AsyncMock(return_value="tok")) as store,
        patch(f"{_MODULE}.send_magic_link_email") as send,
    ):
        yield {
            "verify_domain": verify_domain,
            "reserve": reserve,
            "release": release,
            "store": store,
            "send": send,
        }


@pytest.fixture
def not_sso_only() -> Iterator[None]:
    with patch(f"{_MODULE}.is_sso_only", return_value=False):
        yield


def _playground(hooks: dict[str, Any]) -> Callable[..., Any]:
    """The EE helper on the playground: a hook that exists comes back as is.
    A missing one comes back as a function that returns the fallback, as the
    real helper does without EE."""

    def fetch(_module: str, attribute: str, noop_return_value: Any = None) -> Any:
        if attribute in hooks:
            return hooks[attribute]
        return lambda *_args, **_kwargs: noop_return_value

    return fetch


class TestRequest:
    @pytest.mark.usefixtures("mail_is_configured")
    def test_a_work_address_gets_a_link_and_nothing_else(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        response = client.post(
            "/auth/magic-link/request",
            json={"email": EMAIL, "start_new_team": True, "next_url": "/app?x=1"},
            cookies={"referral_source": "ads"},
        )

        assert response.status_code == 202
        assert response.json() == {"email": "someone@example.com"}
        (stored,) = address_passes["store"].await_args.args
        assert stored.model_dump(exclude={"browser_hash"}) == MagicLinkRecord(
            email="someone@example.com",
            start_new_team=True,
            next_url="/app?x=1",
            referral_source="ads",
        ).model_dump(exclude={"browser_hash"})
        # This browser holds the secret; the record holds only its hash.
        secret = response.cookies.get(MAGIC_LINK_BROWSER_COOKIE)
        assert secret
        assert stored.browser_hash == hashlib.sha256(secret.encode()).hexdigest()
        set_cookie = response.headers["set-cookie"].lower()
        assert "httponly" in set_cookie and "samesite=lax" in set_cookie
        address_passes["send"].assert_called_once_with(
            "someone@example.com", f"{WEB_DOMAIN}/auth/magic-link?token=tok"
        )
        # Sign-in rules only: the new-account rules wait for redemption, when
        # it is known whether the address has an account.
        address_passes["verify_domain"].assert_called_once_with(
            "someone@example.com", valid_email_domains=()
        )
        address_passes["reserve"].assert_awaited_once_with("someone@example.com")

    @pytest.mark.usefixtures("mail_is_configured", "not_sso_only")
    def test_an_existing_dotted_gmail_address_can_ask_for_a_link(
        self, client: TestClient
    ) -> None:
        """The real domain check on cloud. Dotted Gmail is refused only for a
        new account, and Google sign-in may have created one."""
        settings = MagicMock()
        settings.valid_email_domains = ()
        with (
            patch("onyx.auth.users.MULTI_TENANT", True),
            patch("onyx.auth.users.is_disposable_email", return_value=False),
            patch(f"{_MODULE}.get_security_settings", return_value=settings),
            patch(f"{_MODULE}.IS_PLAYGROUND", False),
            patch(f"{_MODULE}.reserve_send", AsyncMock(return_value="claim")),
            patch(f"{_MODULE}.store_magic_link", AsyncMock(return_value="tok")),
            patch(f"{_MODULE}.send_magic_link_email") as send,
        ):
            response = client.post(
                "/auth/magic-link/request", json={"email": "jane.doe@gmail.com"}
            )

        assert response.status_code == 202
        send.assert_called_once()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_an_off_site_next_url_is_dropped_before_storage(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        response = client.post(
            "/auth/magic-link/request",
            json={"email": EMAIL, "next_url": "https://evil.example.com/"},
        )

        assert response.status_code == 202
        (record,) = address_passes["store"].await_args.args
        assert record.next_url == "/"
        assert record.start_new_team is False
        assert record.referral_source is None

    @pytest.mark.usefixtures("mail_is_configured")
    def test_a_disposable_address_is_refused_before_any_email(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        address_passes["verify_domain"].side_effect = OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Disposable email addresses are not allowed."
        )

        response = client.post(
            "/auth/magic-link/request", json={"email": "x@mailinator.com"}
        )

        assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code
        address_passes["store"].assert_not_awaited()
        address_passes["send"].assert_not_called()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_the_playground_refuses_a_free_mail_address_before_any_email(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        def refuse(_email: str) -> None:
            raise OnyxError(OnyxErrorCode.REGISTRATION_DISABLED, "PLAYGROUND_FREE_MAIL")

        with (
            patch(f"{_MODULE}.IS_PLAYGROUND", True),
            patch(
                f"{_MODULE}.fetch_ee_implementation_or_noop",
                _playground({"check_playground_address": refuse}),
            ),
        ):
            response = client.post(
                "/auth/magic-link/request", json={"email": "someone@gmail.com"}
            )

        assert response.status_code == OnyxErrorCode.REGISTRATION_DISABLED.status_code
        assert response.json()["detail"] == "PLAYGROUND_FREE_MAIL"
        address_passes["store"].assert_not_awaited()
        address_passes["send"].assert_not_called()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_off_the_playground_the_address_rule_is_not_asked(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        with (
            patch(f"{_MODULE}.IS_PLAYGROUND", False),
            patch(f"{_MODULE}.fetch_ee_implementation_or_noop") as fetch,
        ):
            response = client.post(
                "/auth/magic-link/request", json={"email": "someone@gmail.com"}
            )

        assert response.status_code == 202
        fetch.assert_not_called()
        address_passes["send"].assert_called_once()

    def test_without_an_email_sender_nothing_is_stored(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        with patch(f"{_MODULE}.EMAIL_CONFIGURED", False):
            response = client.post("/auth/magic-link/request", json={"email": EMAIL})

        assert response.status_code == OnyxErrorCode.SERVICE_UNAVAILABLE.status_code
        address_passes["store"].assert_not_awaited()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_sso_only_sends_nothing(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        with patch(f"{_MODULE}.is_sso_only", return_value=True):
            response = client.post("/auth/magic-link/request", json={"email": EMAIL})

        assert response.status_code == OnyxErrorCode.REGISTRATION_DISABLED.status_code
        assert response.json()["detail"] == MAGIC_LINK_USE_SSO_CODE
        address_passes["store"].assert_not_awaited()
        address_passes["send"].assert_not_called()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_unreadable_settings_send_nothing(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        with patch(f"{_MODULE}.is_sso_only", side_effect=RuntimeError("db down")):
            response = client.post("/auth/magic-link/request", json={"email": EMAIL})

        assert response.status_code == OnyxErrorCode.SERVICE_UNAVAILABLE.status_code
        address_passes["reserve"].assert_not_awaited()
        address_passes["send"].assert_not_called()

    @pytest.mark.usefixtures("mail_is_configured")
    def test_a_failed_send_is_reported(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        address_passes["send"].side_effect = RuntimeError("smtp down")

        response = client.post("/auth/magic-link/request", json={"email": EMAIL})

        assert response.status_code == OnyxErrorCode.SERVICE_UNAVAILABLE.status_code
        assert response.json()["detail"] == "Failed to send the sign-in email."
        # Nothing reached the inbox, so the address may ask again at once.
        address_passes["release"].assert_awaited_once_with(
            "someone@example.com", "claim"
        )
        assert MAGIC_LINK_BROWSER_COOKIE not in response.cookies

    @pytest.mark.usefixtures("mail_is_configured")
    def test_one_email_per_address_a_minute(
        self, client: TestClient, address_passes: dict[str, MagicMock]
    ) -> None:
        address_passes["reserve"].return_value = None

        response = client.post("/auth/magic-link/request", json={"email": EMAIL})

        assert response.status_code == OnyxErrorCode.RATE_LIMITED.status_code
        address_passes["store"].assert_not_awaited()
        address_passes["send"].assert_not_called()


BROWSER_SECRET = "this-browser-asked"
RECORD = MagicLinkRecord(
    email="someone@example.com",
    start_new_team=True,
    next_url="/app",
    referral_source="ads",
    browser_hash=hashlib.sha256(BROWSER_SECRET.encode()).hexdigest(),
)
TEAM_CHOICE = OnyxError(OnyxErrorCode.REGISTRATION_DISABLED, "PLAYGROUND_ACTIVE_TENANT")


def _login_response() -> Response:
    response = Response()
    response.set_cookie("fastapiusersauth", "session-token")
    response.headers.append("set-cookie", "second=2; Path=/")
    return response


def _user(*, is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.is_active = is_active
    return user


def _is_team_choice(error: OnyxError) -> bool:
    return error.detail == "PLAYGROUND_ACTIVE_TENANT"


@pytest.mark.usefixtures("not_sso_only")
class TestRedeem:
    @pytest.fixture(autouse=True)
    def peeked(self, client: TestClient) -> Iterator[AsyncMock]:
        """By default the link is opened in the browser that asked for it."""
        client.cookies.set(MAGIC_LINK_BROWSER_COOKIE, BROWSER_SECRET)
        with patch(
            f"{_MODULE}.peek_magic_link", AsyncMock(return_value=RECORD)
        ) as peek:
            yield peek

    def test_a_good_token_signs_in_and_sets_the_cookies(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        user = _user()
        user_manager.magic_link_login.return_value = user
        with (
            patch(f"{_MODULE}.consume_magic_link", AsyncMock(return_value=RECORD)),
            patch.object(
                magic_link_api.auth_backend,
                "login",
                AsyncMock(return_value=_login_response()),
            ),
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == 200
        assert response.json() == {
            "state": "signed_in",
            "next_url": "/app",
            "team_choice_token": None,
        }
        cookies = response.headers.get_list("set-cookie")
        assert any(c.startswith("fastapiusersauth=session-token") for c in cookies)
        assert any(c.startswith("second=2") for c in cookies)

        kwargs: dict[str, Any] = user_manager.magic_link_login.await_args.kwargs
        assert user_manager.magic_link_login.await_args.args[0] == RECORD.email
        assert kwargs == {"start_new_team": True, "referral_source": "ads"}
        user_manager.on_after_login.assert_awaited_once()

    def test_a_used_or_expired_token_is_one_generic_refusal(
        self, client: TestClient, user_manager: MagicMock, peeked: AsyncMock
    ) -> None:
        peeked.return_value = None
        with patch(f"{_MODULE}.consume_magic_link", AsyncMock()) as consume:
            response = client.post("/auth/magic-link/redeem", json={"token": "old"})
        consume.assert_not_awaited()

        assert response.status_code == OnyxErrorCode.INVALID_TOKEN.status_code
        assert response.json()["detail"] == MAGIC_LINK_INVALID_CODE
        user_manager.magic_link_login.assert_not_awaited()
        assert "set-cookie" not in response.headers

    def test_a_refusal_reaches_the_page_as_its_code(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        user_manager.magic_link_login.side_effect = OnyxError(
            OnyxErrorCode.REGISTRATION_DISABLED, "PLAYGROUND_EMAIL_USED"
        )
        with patch(f"{_MODULE}.consume_magic_link", AsyncMock(return_value=RECORD)):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == OnyxErrorCode.REGISTRATION_DISABLED.status_code
        assert response.json()["detail"] == "PLAYGROUND_EMAIL_USED"
        assert "set-cookie" not in response.headers

    def test_a_running_trial_from_the_domain_becomes_a_question(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        first_click = RECORD.model_copy(update={"start_new_team": False})
        user_manager.magic_link_login.side_effect = TEAM_CHOICE
        with (
            patch(f"{_MODULE}.consume_magic_link", AsyncMock(return_value=first_click)),
            patch(
                f"{_MODULE}.store_magic_link", AsyncMock(return_value="tok2")
            ) as store,
            patch(
                f"{_MODULE}.fetch_ee_implementation_or_noop",
                _playground({"is_team_choice_refusal": _is_team_choice}),
            ),
            patch.object(magic_link_api.auth_backend, "login", AsyncMock()) as login,
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == 200
        assert response.json() == {
            "state": "team_choice",
            "next_url": None,
            "team_choice_token": "tok2",
        }
        # The same address and landing, with only the choice changed.
        # Only the choice changes, and the token never leaves this page.
        store.assert_awaited_once_with(
            first_click.model_copy(update={"start_new_team": True, "proven": True})
        )
        login.assert_not_awaited()
        assert "set-cookie" not in response.headers

    def test_the_question_is_asked_once(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        # RECORD already carries the choice; a refusal now is final.
        user_manager.magic_link_login.side_effect = TEAM_CHOICE
        with (
            patch(f"{_MODULE}.consume_magic_link", AsyncMock(return_value=RECORD)),
            patch(f"{_MODULE}.store_magic_link", AsyncMock()) as store,
            patch(
                f"{_MODULE}.fetch_ee_implementation_or_noop",
                _playground({"is_team_choice_refusal": _is_team_choice}),
            ),
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok2"})

        assert response.status_code == OnyxErrorCode.REGISTRATION_DISABLED.status_code
        assert response.json()["detail"] == "PLAYGROUND_ACTIVE_TENANT"
        store.assert_not_awaited()

    def test_without_ee_a_refusal_stays_a_refusal(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        """The real helper with EE off. Its fallback must answer "not a
        question", or every refusal would come back as team_choice."""
        first_click = RECORD.model_copy(update={"start_new_team": False})
        user_manager.magic_link_login.side_effect = OnyxError(
            OnyxErrorCode.UNAUTHORIZED, "You are not invited."
        )
        was_ee = global_version.is_ee_version()
        global_version.unset_ee()
        try:
            with (
                patch(
                    f"{_MODULE}.consume_magic_link",
                    AsyncMock(return_value=first_click),
                ),
                patch(f"{_MODULE}.store_magic_link", AsyncMock()) as store,
            ):
                response = client.post("/auth/magic-link/redeem", json={"token": "tok"})
        finally:
            if was_ee:
                global_version.set_ee()

        assert response.status_code == OnyxErrorCode.UNAUTHORIZED.status_code
        assert response.json()["detail"] == "You are not invited."
        store.assert_not_awaited()

    def test_sso_only_keeps_the_token_unused(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        with (
            patch(f"{_MODULE}.is_sso_only", return_value=True),
            patch(f"{_MODULE}.consume_magic_link", AsyncMock()) as consume,
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == OnyxErrorCode.REGISTRATION_DISABLED.status_code
        assert response.json()["detail"] == MAGIC_LINK_USE_SSO_CODE
        consume.assert_not_awaited()
        user_manager.magic_link_login.assert_not_awaited()

    def test_unreadable_settings_keep_the_token_unused(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        with (
            patch(f"{_MODULE}.is_sso_only", side_effect=RuntimeError("db down")),
            patch(f"{_MODULE}.consume_magic_link", AsyncMock()) as consume,
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == OnyxErrorCode.SERVICE_UNAVAILABLE.status_code
        consume.assert_not_awaited()
        user_manager.magic_link_login.assert_not_awaited()

    def test_a_disabled_account_is_not_signed_in(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        user_manager.magic_link_login.return_value = _user(is_active=False)
        with (
            patch(f"{_MODULE}.consume_magic_link", AsyncMock(return_value=RECORD)),
            patch.object(magic_link_api.auth_backend, "login", AsyncMock()) as login,
        ):
            response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == OnyxErrorCode.VALIDATION_ERROR.status_code
        login.assert_not_awaited()


class TestRedeemElsewhere:
    """A link opened in another browser than the one that asked for it."""

    @pytest.fixture(autouse=True)
    def setup(
        self, client: TestClient, user_manager: MagicMock
    ) -> Iterator[dict[str, AsyncMock]]:
        client.cookies.clear()
        user_manager.magic_link_login.return_value = _user()
        with (
            patch(f"{_MODULE}.is_sso_only", return_value=False),
            patch(f"{_MODULE}.peek_magic_link", AsyncMock(return_value=RECORD)) as peek,
            patch(
                f"{_MODULE}.consume_magic_link", AsyncMock(return_value=RECORD)
            ) as consume,
            patch.object(
                magic_link_api.auth_backend,
                "login",
                AsyncMock(return_value=_login_response()),
            ),
        ):
            yield {"peek": peek, "consume": consume}

    def test_asks_for_the_address_and_keeps_the_token(
        self,
        client: TestClient,
        user_manager: MagicMock,
        setup: dict[str, AsyncMock],
    ) -> None:
        response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.status_code == 200
        assert response.json()["state"] == "confirm_email"
        setup["consume"].assert_not_awaited()
        user_manager.magic_link_login.assert_not_awaited()

    def test_another_browsers_cookie_is_not_this_one(
        self, client: TestClient, setup: dict[str, AsyncMock]
    ) -> None:
        client.cookies.set(MAGIC_LINK_BROWSER_COOKIE, "some-other-request")

        response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.json()["state"] == "confirm_email"
        setup["consume"].assert_not_awaited()

    def test_the_right_address_signs_in(
        self, client: TestClient, user_manager: MagicMock
    ) -> None:
        response = client.post(
            "/auth/magic-link/redeem",
            json={"token": "tok", "email": " Someone@Example.com "},
        )

        assert response.status_code == 200
        assert response.json()["state"] == "signed_in"
        user_manager.magic_link_login.assert_awaited_once()

    def test_a_wrong_address_uses_the_link_up(
        self,
        client: TestClient,
        user_manager: MagicMock,
        setup: dict[str, AsyncMock],
    ) -> None:
        response = client.post(
            "/auth/magic-link/redeem",
            json={"token": "tok", "email": "victim@example.com"},
        )

        assert response.status_code == OnyxErrorCode.UNAUTHORIZED.status_code
        assert response.json()["detail"] == MAGIC_LINK_WRONG_EMAIL_CODE
        # One try, so the address cannot be guessed.
        setup["consume"].assert_awaited_once_with("tok")
        user_manager.magic_link_login.assert_not_awaited()

    @pytest.mark.parametrize(
        "typed", ["someone@example.com", "victim@example.com"], ids=["right", "wrong"]
    )
    def test_a_link_used_up_meanwhile_gives_one_answer_for_any_address(
        self,
        client: TestClient,
        user_manager: MagicMock,
        setup: dict[str, AsyncMock],
        typed: str,
    ) -> None:
        """Parallel guesses all read the record before one uses it up. The
        others must answer the same, right address or wrong, or the
        difference would reveal the address."""
        setup["consume"].return_value = None

        response = client.post(
            "/auth/magic-link/redeem", json={"token": "tok", "email": typed}
        )

        assert response.status_code == OnyxErrorCode.INVALID_TOKEN.status_code
        assert response.json()["detail"] == "MAGIC_LINK_INVALID"
        user_manager.magic_link_login.assert_not_awaited()

    def test_a_record_without_a_browser_always_asks(
        self, client: TestClient, setup: dict[str, AsyncMock]
    ) -> None:
        setup["peek"].return_value = RECORD.model_copy(update={"browser_hash": None})
        client.cookies.set(MAGIC_LINK_BROWSER_COOKIE, BROWSER_SECRET)

        response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        assert response.json()["state"] == "confirm_email"

    def test_a_proven_record_needs_no_browser(
        self, client: TestClient, setup: dict[str, AsyncMock]
    ) -> None:
        proven = RECORD.model_copy(update={"browser_hash": None, "proven": True})
        setup["peek"].return_value = proven
        setup["consume"].return_value = proven

        response = client.post("/auth/magic-link/redeem", json={"token": "tok2"})

        assert response.json()["state"] == "signed_in"

    def test_signing_in_clears_the_browser_cookie(self, client: TestClient) -> None:
        client.cookies.set(MAGIC_LINK_BROWSER_COOKIE, BROWSER_SECRET)

        response = client.post("/auth/magic-link/redeem", json={"token": "tok"})

        cleared = [
            c
            for c in response.headers.get_list("set-cookie")
            if c.startswith(f"{MAGIC_LINK_BROWSER_COOKIE}=")
        ]
        assert cleared and "max-age=0" in cleared[0].lower()


@pytest.mark.parametrize(
    ("multi_tenant", "password_auth_enabled", "sso_only"),
    [
        (False, False, True),
        (False, True, False),
        # Cloud has no password switch, so SSO is never the only way in.
        (True, False, False),
    ],
)
def test_sso_only_follows_the_password_switch(
    multi_tenant: bool, password_auth_enabled: bool, sso_only: bool
) -> None:
    settings = MagicMock()
    settings.password_auth_enabled = password_auth_enabled
    with (
        patch.object(magic_link, "MULTI_TENANT", multi_tenant),
        patch.object(
            magic_link, "get_security_settings", return_value=settings
        ) as get_settings,
    ):
        assert magic_link.is_sso_only() is sso_only
    if not multi_tenant:
        # Strict by default: a failed read must not fall back to passwords on.
        get_settings.assert_called_once_with(allow_fallback=False)


def test_a_failed_settings_read_is_not_taken_as_passwords_on() -> None:
    with (
        patch.object(magic_link, "MULTI_TENANT", False),
        patch.object(
            magic_link, "get_security_settings", side_effect=RuntimeError("db down")
        ),
    ):
        with pytest.raises(RuntimeError):
            magic_link.is_sso_only()


class _SlotCache:
    """The two cache calls the send slot uses, with expiry done by hand."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def set_if_absent(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        if key in self.values:
            return False
        self.values[key] = value.encode("utf-8")
        return True

    def delete_if_value(self, key: str, expected: bytes) -> bool:
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True


@pytest.mark.asyncio
async def test_a_late_failure_leaves_a_newer_slot_alone() -> None:
    """A send that fails after its slot expired must not clear the slot a newer
    request took for the same address."""
    cache = _SlotCache()
    email = "someone@example.com"
    with patch.object(magic_link, "get_shared_cache_backend", return_value=cache):
        old_claim = await magic_link.reserve_send(email)
        assert old_claim is not None
        cache.values.clear()  # the old slot expires while its send hangs
        new_claim = await magic_link.reserve_send(email)
        assert new_claim is not None

        await magic_link.release_send(email, old_claim)
        assert await magic_link.reserve_send(email) is None

        await magic_link.release_send(email, new_claim)
        assert await magic_link.reserve_send(email) is not None
