import datetime
from typing import Any, NamedTuple

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.auth.users import verify_email_domain, verify_email_is_invited
from onyx.configs.onyxbot_configs import (
    ONYX_BOT_FEEDBACK_REMINDER,
    ONYX_BOT_REACT_EMOJI,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.models import ChannelConfig, SlackChannelConfig, User
from onyx.db.user_preferences import activate_user
from onyx.db.users import add_slack_user_if_not_exists, get_user_by_email
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.onyxbot.slack.blocks import get_feedback_reminder_blocks
from onyx.onyxbot.slack.handlers.handle_regular_answer import handle_regular_answer
from onyx.onyxbot.slack.handlers.handle_standard_answers import handle_standard_answers
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import (
    fetch_slack_user_ids_from_emails,
    fetch_user_ids_from_groups,
    respond_in_thread_or_channel,
    slack_usage_report,
    update_emote_react,
)
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import OnyxLoggingAdapter, setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import SLACK_CHANNEL_ID
from shared_configs.contextvars import get_current_tenant_id

logger_base = setup_logger()

_SEAT_LIMIT_TEXT = (
    "We weren't able to respond because your organization "
    "has reached its user seat limit. Please contact your "
    "Onyx administrator to add more seats."
)


def send_msg_ack_to_user(details: SlackMessageInfo, client: WebClient) -> None:
    if details.is_slash_command and details.sender_id:
        respond_in_thread_or_channel(
            client=client,
            channel=details.channel_to_respond,
            thread_ts=details.msg_to_respond,
            receiver_ids=[details.sender_id],
            text="Hi, we're evaluating your query :face_with_monocle:",
        )
        return

    update_emote_react(
        emoji=ONYX_BOT_REACT_EMOJI,
        channel=details.channel_to_respond,
        message_ts=details.msg_to_respond,
        remove=False,
        client=client,
    )


def schedule_feedback_reminder(
    details: SlackMessageInfo, include_followup: bool, client: WebClient
) -> str | None:
    logger = setup_logger(extra={SLACK_CHANNEL_ID: details.channel_to_respond})

    if not ONYX_BOT_FEEDBACK_REMINDER:
        logger.info("Scheduled feedback reminder disabled...")
        return None

    try:
        permalink = client.chat_getPermalink(
            channel=details.channel_to_respond,
            message_ts=details.msg_to_respond,  # ty: ignore[invalid-argument-type]
        )
    except SlackApiError as e:
        logger.error("Unable to generate the feedback reminder permalink: %s", e)
        return None

    now = datetime.datetime.now()
    future = now + datetime.timedelta(minutes=ONYX_BOT_FEEDBACK_REMINDER)

    try:
        response = client.chat_scheduleMessage(
            channel=details.sender_id,  # ty: ignore[invalid-argument-type]
            post_at=int(future.timestamp()),
            blocks=[
                get_feedback_reminder_blocks(
                    thread_link=permalink.data[  # ty: ignore[invalid-argument-type]
                        "permalink"
                    ],
                    include_followup=include_followup,
                )
            ],
            text="",
        )
        logger.info("Scheduled feedback reminder configured")
        return response.data[  # ty: ignore[invalid-argument-type]
            "scheduled_message_id"
        ]
    except SlackApiError as e:
        logger.error("Unable to generate the feedback reminder message: %s", e)
        return None


def remove_scheduled_feedback_reminder(
    client: WebClient, channel: str | None, msg_id: str
) -> None:
    logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

    try:
        client.chat_deleteScheduledMessage(
            channel=channel,  # ty: ignore[invalid-argument-type]
            scheduled_message_id=msg_id,
        )
        logger.info("Scheduled feedback reminder deleted")
    except SlackApiError as e:
        if e.response["error"] == "invalid_scheduled_message_id":
            logger.info(
                "Unable to delete the scheduled message. It must have already been posted"
            )


def _resolve_allowlist_user_ids(
    channel_conf: ChannelConfig | None,
    client: WebClient,
) -> tuple[list[str] | None, list[str]]:
    """Resolve `respond_member_group_list` (emails + group names) to Slack user IDs.

    Returns (resolved_user_ids, missing_entries). `resolved_user_ids` is `None`
    when no allowlist is configured, meaning the bot has no invocation gate or
    response-visibility scope for the channel.
    """
    allowlist = (channel_conf or {}).get("respond_member_group_list") or None
    if not allowlist:
        return None, []

    user_ids, missing_ids = fetch_slack_user_ids_from_emails(allowlist, client)
    group_user_ids, missing = fetch_user_ids_from_groups(missing_ids, client)
    resolved = list(set(user_ids + group_user_ids))
    return resolved, missing


class _Denial(NamedTuple):
    """A reason to not answer, plus the message sent back to the sender."""

    log_msg: str
    text: str
    # Ephemeral for denials about the sender, so they never post publicly in
    # the channel.
    ephemeral: bool = False


def _usage_report_action(message_info: SlackMessageInfo) -> str:
    if message_info.is_slash_command:
        return "slack_slash_message"
    if message_info.bypass_filters:
        return "slack_tag_message"
    if message_info.is_bot_dm:
        return "slack_dm_message"
    return "slack_message"


def _skip_reason(
    message_info: SlackMessageInfo,
    slack_channel_config: SlackChannelConfig,
    channel_conf: ChannelConfig | None,
    document_set_names: list[str] | None,
    logger: OnyxLoggingAdapter,
) -> str | None:
    """Return why the bot must stay silent, or None to keep going."""
    respond_tag_only = False

    if channel_conf:
        if (
            not message_info.bypass_filters
            and "answer_filters" in channel_conf
            and "questionmark_prefilter" in channel_conf["answer_filters"]
            and "?" not in message_info.thread_messages[-1].message
        ):
            return "Skipping message since it does not contain a question mark"

        logger.info(
            "Found slack bot config for channel. Restricting bot to use document sets: %s, validity checks enabled: %s",
            document_set_names,
            channel_conf.get("answer_filters", "NA"),
        )

        respond_tag_only = channel_conf.get("respond_tag_only") or False

    # Only default config can be disabled.
    # If channel config is disabled, bot should not respond to this message (including DMs)
    if slack_channel_config.channel_config.get("disabled"):
        return "Skipping message: OnyxBot is disabled for this channel"

    # If bot should only respond to tags and is not tagged nor in a DM, skip message
    if (
        respond_tag_only
        and not message_info.bypass_filters
        and not message_info.is_bot_dm
    ):
        return "Skipping message: OnyxBot only responds to tags in this channel"

    return None


def _check_seat_availability(db_session: Session) -> Any:
    """Run the EE seat check. Returns None in CE, where the noop applies."""
    check_seat_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license",
        "check_seat_availability",
        None,
    )
    return check_seat_fn(db_session=db_session)


def _invalidate_license_cache() -> None:
    invalidate_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license",
        "invalidate_license_cache",
        None,
    )
    invalidate_fn()


def _email_policy_denial(email: str) -> _Denial | None:
    """Invite-only and email-domain policies gate provisioning like any
    self-serve signup (JWT and OAuth pair the same checks). BOT accounts were
    provisioned by the bot itself, never re-checked."""
    try:
        verify_email_is_invited(email)
        verify_email_domain(
            email,
            valid_email_domains=get_security_settings().valid_email_domains,
        )
    except OnyxError as e:
        if e.error_code not in (
            OnyxErrorCode.UNAUTHORIZED,
            OnyxErrorCode.INVALID_INPUT,
        ):
            raise
        return _Denial(
            f"Blocked Slack-bot provisioning of {email}: {e.detail}",
            (
                "We weren't able to respond because this workspace "
                "is invite-only and your email has not been "
                "invited. Please ask your Onyx administrator for "
                "an invite."
                if e.error_code == OnyxErrorCode.UNAUTHORIZED
                else "We weren't able to respond because your email "
                "address is not allowed in this workspace. Please "
                "contact your Onyx administrator."
            ),
            ephemeral=True,
        )

    return None


def _seat_denial(
    db_session: Session,
    existing_user: User | None,
    email: str,
    logger: OnyxLoggingAdapter,
) -> _Denial | None:
    """Check seats for the sender and reactivate a deactivated bot user."""
    if existing_user is None:
        # New user — check seat availability before creating
        seat_result = _check_seat_availability(db_session)
        if seat_result is not None and not seat_result.available:
            return _Denial(
                f"Blocked new Slack user {email}: {seat_result.error_message}",
                (
                    "We weren't able to respond because your organization "
                    "has reached its user seat limit. Since this is your "
                    "first time interacting with the bot, a new account "
                    "could not be created for you. Please contact your "
                    "Onyx administrator to add more seats."
                ),
            )

    elif not existing_user.is_active and existing_user.account_type == AccountType.BOT:
        # Lock + check on the same session that commits activate_user.
        acquire_lock_fn = fetch_ee_implementation_or_noop(
            "onyx.db.license",
            "acquire_seat_lock",
            None,
        )
        acquire_lock_fn(db_session, get_current_tenant_id())
        seat_result = _check_seat_availability(db_session)
        if seat_result is not None and not seat_result.available:
            return _Denial(
                f"Blocked inactive Slack user {email}: {seat_result.error_message}",
                (
                    "We weren't able to respond because your organization "
                    "has reached its user seat limit. Your account is "
                    "currently deactivated and cannot be reactivated "
                    "until more seats are available. Please contact "
                    "your Onyx administrator."
                ),
            )

        activate_user(existing_user, db_session)
        _invalidate_license_cache()
        logger.info("Reactivated inactive Slack user %s", email)

    elif existing_user.account_type == AccountType.EXT_PERM_USER:
        # Pre-check so the user gets a Slack-side message; the
        # locked enforcer below is defense-in-depth.
        seat_result = _check_seat_availability(db_session)
        if seat_result is not None and not seat_result.available:
            return _Denial(
                f"Blocked Slack-bot promotion of {email}: {seat_result.error_message}",
                _SEAT_LIMIT_TEXT,
            )

    return None


def _slack_seat_enforcer(session: Session, seats_needed: int) -> None:
    """Defense-in-depth: locks + checks on the same session that commits the
    EXT_PERM_USER -> BOT promotion."""
    acquire_lock_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license",
        "acquire_seat_lock",
        None,
    )
    check_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license",
        "check_seat_availability",
        None,
    )
    acquire_lock_fn(session, get_current_tenant_id())
    result = check_fn(session, seats_needed=seats_needed)
    if result is not None and not result.available:
        raise OnyxError(OnyxErrorCode.SEAT_LIMIT_EXCEEDED, result.error_message)


def _provision_slack_user(
    db_session: Session,
    message_info: SlackMessageInfo,
    logger: OnyxLoggingAdapter,
) -> _Denial | None:
    """Create, promote, or reactivate the Onyx user for the Slack sender.

    Returns a `_Denial` when a policy or the seat limit blocks the message.
    """
    email = message_info.email
    if not email:
        return None

    existing_user = get_user_by_email(email, db_session)

    # True when this message provisions an account (new user or
    # EXT_PERM_USER promotion). Read before add_slack_user_if_not_exists
    # promotes in place, else the cache invalidation below is skipped.
    provisions_account: bool = existing_user is None or (
        existing_user.account_type == AccountType.EXT_PERM_USER
    )

    if provisions_account:
        policy_denial = _email_policy_denial(email)
        if policy_denial is not None:
            return policy_denial

    seat_denial = _seat_denial(db_session, existing_user, email, logger)
    if seat_denial is not None:
        return seat_denial

    try:
        add_slack_user_if_not_exists(
            db_session,
            email,
            enforce_seat_check=_slack_seat_enforcer,
        )
    except OnyxError as e:
        if e.error_code != OnyxErrorCode.SEAT_LIMIT_EXCEEDED:
            raise
        return _Denial(
            f"Blocked Slack-bot user creation/promotion for {email}: {e.detail}",
            _SEAT_LIMIT_TEXT,
        )
    else:
        if provisions_account:
            _invalidate_license_cache()

    return None


def handle_message(
    message_info: SlackMessageInfo,
    slack_channel_config: SlackChannelConfig,
    client: WebClient,
    feedback_reminder_id: str | None,
) -> bool:
    """Potentially respond to the user message depending on filters and if an answer was generated

    Returns True if need to respond with an additional message to the user(s) after this
    function is finished. True indicates an unexpected failure that needs to be communicated
    Query thrown out by filters due to config does not count as a failure that should be notified
    Onyx failing to answer/retrieve docs does count and should be notified
    """
    channel = message_info.channel_to_respond

    logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

    sender_id = message_info.sender_id
    is_slash_command = message_info.is_slash_command

    channel_conf: ChannelConfig | None = (
        slack_channel_config.channel_config
        if slack_channel_config and slack_channel_config.channel_config
        else None
    )

    # Resolve the allowlist once. Drives both the invocation gate (who can
    # trigger the bot) and the response-visibility scope (who sees responses).
    # `None` means no allowlist configured -> no gate, no visibility scoping.
    allowed_user_ids, missing_allowlist_entries = _resolve_allowlist_user_ids(
        channel_conf, client
    )
    if missing_allowlist_entries:
        logger.warning(
            "Failed to find these users/groups in respond_member_group_list: %s",
            missing_allowlist_entries,
        )
        if allowed_user_ids is not None and not allowed_user_ids:
            # Allowlist is configured but every entry failed to resolve — bot is
            # silent to everyone until lookups recover. Surface at ERROR so it
            # alerts instead of hiding in WARN noise.
            logger.error(
                "respond_member_group_list is configured but no entries resolved; "
                "OnyxBot will be silent in this channel until lookups recover"
            )

    # Invocation gate: drop non-allowlisted senders before emitting telemetry or
    # creating a Slack-user account row (which would consume a license seat).
    # Applies even to direct @-tags / DMs — this is a license-seat gate, not a
    # content filter.
    if allowed_user_ids is not None and (
        sender_id is None or sender_id not in allowed_user_ids
    ):
        logger.info(
            "Skipping message: sender %s is not in respond_member_group_list",
            sender_id,
        )
        return False

    slack_usage_report(
        action=_usage_report_action(message_info), sender_id=sender_id, client=client
    )

    persona = slack_channel_config.persona if slack_channel_config else None
    document_set_names: list[str] | None = (
        [document_set.name for document_set in persona.document_sets]
        if persona
        else None
    )

    skip_reason = _skip_reason(
        message_info, slack_channel_config, channel_conf, document_set_names, logger
    )
    if skip_reason is not None:
        logger.info(skip_reason)
        return False

    # Reuses the resolved allowlist as the ephemeral response-visibility scope.
    send_to: list[str] | None = allowed_user_ids

    # If configured to respond to team members only, then cannot be used with a /OnyxBot command
    # which would just respond to the sender
    if send_to and is_slash_command and sender_id:
        respond_in_thread_or_channel(
            client=client,
            channel=channel,
            receiver_ids=[sender_id],
            text="The OnyxBot slash command is not enabled for this channel",
            thread_ts=None,
        )

    try:
        send_msg_ack_to_user(message_info, client)
    except SlackApiError as e:
        logger.error("Was not able to react to user message due to: %s", e)

    def _deny(denial: _Denial) -> bool:
        """Tell the sender the bot will not respond. Always returns False."""
        logger.info(denial.log_msg)
        respond_in_thread_or_channel(
            client=client,
            channel=channel,
            thread_ts=message_info.msg_to_respond,
            receiver_ids=(
                [message_info.sender_id]
                if denial.ephemeral and message_info.sender_id
                else None
            ),
            text=denial.text,
        )
        return False

    with get_session_with_current_tenant() as db_session:
        denial = _provision_slack_user(db_session, message_info, logger)
        if denial is not None:
            return _deny(denial)

        # first check if we need to respond with a standard answer
        # standard answers should be published in a thread
        used_standard_answer = handle_standard_answers(
            message_info=message_info,
            receiver_ids=send_to,
            slack_channel_config=slack_channel_config,
            logger=logger,
            client=client,
            db_session=db_session,
        )
        if used_standard_answer:
            return False

        # if no standard answer applies, try a regular answer
        issue_with_regular_answer = handle_regular_answer(
            message_info=message_info,
            slack_channel_config=slack_channel_config,
            receiver_ids=send_to,
            client=client,
            channel=channel,
            logger=logger,
            db_session=db_session,
            feedback_reminder_id=feedback_reminder_id,
        )
        return issue_with_regular_answer
