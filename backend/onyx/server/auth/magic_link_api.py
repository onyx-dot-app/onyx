"""Sign in with a link sent by email. Off unless ``MAGIC_LINK_ENABLED``.

``POST /auth/magic-link/request`` mails a one-time link. Apart from the domain
checks, it answers the same for every address, so it reveals nothing about
accounts. Nothing is created yet.

``POST /auth/magic-link/redeem`` takes the token, signs the user in, and sets
the session cookie. The page the link opens sends this POST, so a mail scanner
that fetches the link cannot use up the token.

On the playground, EE hooks add the free-mail refusal and the join-or-new
question (``ee/onyx/server/tenants/provisioning.py``).
"""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi_users.authentication import Strategy
from fastapi_users.router.common import ErrorCode
from pydantic import BaseModel, EmailStr

from onyx.auth.email_utils import send_magic_link_email
from onyx.auth.magic_link import (
    MagicLinkRecord,
    consume_magic_link,
    store_magic_link,
)
from onyx.auth.users import (
    UserManager,
    auth_backend,
    get_user_manager,
    verify_email_domain,
)
from onyx.configs.app_configs import EMAIL_CONFIGURED, WEB_DOMAIN
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import add_url_params, sanitize_next_url
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import IS_PLAYGROUND

logger = setup_logger()

router = APIRouter(prefix="/auth/magic-link")

# The web page for a link that expired or was already used.
MAGIC_LINK_INVALID_CODE = "MAGIC_LINK_INVALID"

# The page the emailed link opens. It POSTs the token to /redeem.
MAGIC_LINK_WEB_PATH = "/auth/magic-link"

_PLAYGROUND_MODULE = "onyx.server.tenants.provisioning"


class MagicLinkRequest(BaseModel):
    email: EmailStr
    # Playground: the person chose "start a new team" on the join-or-new page.
    start_new_team: bool = False
    next_url: str | None = None


class MagicLinkRequested(BaseModel):
    # The address the link went to, as the "check your email" page shows it.
    email: str


class MagicLinkRedeemRequest(BaseModel):
    token: str


class MagicLinkRedeemed(BaseModel):
    # "signed_in": the session cookie is set; go to next_url.
    # "team_choice": playground only. A team from the domain has a running
    # trial. Ask join or new. "Start a new team" redeems team_choice_token;
    # "join" leaves it to expire.
    state: Literal["signed_in", "team_choice"]
    next_url: str | None = None
    team_choice_token: str | None = None


@router.post("/request", status_code=202)
async def request_magic_link(
    payload: MagicLinkRequest, request: Request
) -> MagicLinkRequested:
    if not EMAIL_CONFIGURED:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Email sending has not been configured for this deployment.",
        )

    email = payload.email.lower()
    # Decided by the address alone, so refused before any email goes out.
    verify_email_domain(
        email,
        valid_email_domains=get_security_settings().valid_email_domains,
        is_registration=True,
    )
    if IS_PLAYGROUND:
        fetch_ee_implementation_or_noop(
            _PLAYGROUND_MODULE, "check_playground_address", None
        )(email)

    record = MagicLinkRecord(
        email=email,
        start_new_team=payload.start_new_team,
        next_url=sanitize_next_url(payload.next_url),
        referral_source=request.cookies.get("referral_source"),
    )
    token = await store_magic_link(record)
    link = add_url_params(f"{WEB_DOMAIN}{MAGIC_LINK_WEB_PATH}", {"token": token})
    try:
        await asyncio.to_thread(send_magic_link_email, email, link)
    except Exception as e:
        logger.exception("Failed to send the magic link email")
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Failed to send the sign-in email."
        ) from e
    return MagicLinkRequested(email=email)


@router.post("/redeem")
async def redeem_magic_link(
    payload: MagicLinkRedeemRequest,
    request: Request,
    response: Response,
    user_manager: UserManager = Depends(get_user_manager),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
) -> MagicLinkRedeemed:
    record = await consume_magic_link(payload.token)
    if record is None:
        # Unknown, expired and already used look the same. The page offers a
        # new link.
        raise OnyxError(OnyxErrorCode.INVALID_TOKEN, MAGIC_LINK_INVALID_CODE)

    try:
        user = await user_manager.magic_link_login(
            record.email,
            request,
            start_new_team=record.start_new_team,
            referral_source=record.referral_source,
        )
    except OnyxError as error:
        # Without EE the helper answers False: no refusal is a question.
        is_team_choice = fetch_ee_implementation_or_noop(
            _PLAYGROUND_MODULE, "is_team_choice_refusal", False
        )
        if record.start_new_team or not is_team_choice(error):
            raise
        # The inbox is proven, so the answer rides a fresh token rather than
        # a second email. Only the choice changes.
        token = await store_magic_link(
            record.model_copy(update={"start_new_team": True})
        )
        return MagicLinkRedeemed(state="team_choice", team_choice_token=token)

    if not user.is_active:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, ErrorCode.LOGIN_BAD_CREDENTIALS)

    login_response = await auth_backend.login(strategy, user)
    await user_manager.on_after_login(user, request, login_response)

    # The session cookie is on the backend's response. Set-Cookie may repeat,
    # so append each rather than assign, which would collapse them.
    for header_name, header_value in login_response.headers.items():
        if header_name.lower() == "set-cookie":
            response.headers.append(header_name, header_value)

    return MagicLinkRedeemed(
        state="signed_in", next_url=sanitize_next_url(record.next_url)
    )
