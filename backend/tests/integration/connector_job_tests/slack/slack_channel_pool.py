"""Reusable Slack test channels shared by concurrent CI runs.

Slot N is the channel pair `onyx-test-pool-public-N` / `onyx-test-pool-private-N`.
A run claims a slot by posting a claim message to the lock channel. The earliest
unexpired claim for a slot wins. Slack gives each message in a channel a unique,
increasing `ts`, so all runs agree on the winner. A later claim can never displace
a winner, and a run that dies leaves a claim that expires after the TTL.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.models import ChannelType
from tests.integration.connector_job_tests.slack.slack_api_utils import (
    SlackApiErrorCode,
    SlackManager,
    create_slack_channel,
    make_paginated_slack_api_call,
    slack_error_code,
)

_POOL_CHANNEL_PREFIX = "onyx-test-pool"
_LOCK_CHANNEL_NAME = f"{_POOL_CHANNEL_PREFIX}-locks"
# Longer than the CI step timeout, so a claim only expires after its run is gone.
_CLAIM_TTL_SECONDS = 30 * 60
# Time for a concurrent claim to show in the lock channel history.
_CLAIM_SETTLE_SECONDS = 3.0
# Upper bound on concurrent runs per workspace, and so on pool channels.
_MAX_POOL_SLOTS = 20
_ALL_SLOTS_BUSY_WAIT_SECONDS = 15.0
_CLAIM_TIMEOUT_SECONDS = 10 * 60


class SlotClaim(BaseModel):
    slot: int
    run_id: str


class PostedClaim(BaseModel):
    claim: SlotClaim
    ts: str


def _index_oldest_by_name(channels: list[ChannelType]) -> dict[str, ChannelType]:
    """Slack allows duplicate names when creates race, so all runs use the oldest."""
    channels_by_name: dict[str, ChannelType] = {}
    for channel in sorted(channels, key=lambda c: (c["created"], c["id"])):
        channels_by_name.setdefault(channel["name"], channel)
    return channels_by_name


def _find_channel(slack_client: WebClient, name: str) -> ChannelType | None:
    return _index_oldest_by_name(SlackManager.list_active_channels(slack_client)).get(
        name
    )


def _get_or_create_channel(
    slack_client: WebClient,
    admin_user_id: str,
    channels_by_name: dict[str, ChannelType],
    name: str,
    is_private: bool,
) -> ChannelType:
    if channel := channels_by_name.get(name):
        return channel
    try:
        return create_slack_channel(
            slack_client=slack_client,
            admin_user_id=admin_user_id,
            name=name,
            is_private=is_private,
        )
    except SlackApiError as e:
        if slack_error_code(e) != SlackApiErrorCode.NAME_TAKEN:
            raise
    # Another run created the channel after our listing.
    if not (channel := _find_channel(slack_client, name)):
        raise RuntimeError(f"Slack channel '{name}' exists but is not visible")
    return channel


def _get_lock_channel(
    slack_client: WebClient,
    admin_user_id: str,
    channels_by_name: dict[str, ChannelType],
) -> ChannelType:
    """Pool channels are only created by their slot holder, but the lock channel can be
    created by concurrent runs. After a create, re-list so every run picks the same one."""
    if channel := channels_by_name.get(_LOCK_CHANNEL_NAME):
        return channel
    _get_or_create_channel(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channels_by_name=channels_by_name,
        name=_LOCK_CHANNEL_NAME,
        is_private=False,
    )
    time.sleep(_CLAIM_SETTLE_SECONDS)
    if not (channel := _find_channel(slack_client, _LOCK_CHANNEL_NAME)):
        raise RuntimeError(f"Slack channel '{_LOCK_CHANNEL_NAME}' is not visible")
    return channel


def _read_live_claims(
    slack_client: WebClient, lock_channel_id: str
) -> list[PostedClaim]:
    oldest = f"{time.time() - _CLAIM_TTL_SECONDS:.6f}"
    claims: list[PostedClaim] = []
    for result in make_paginated_slack_api_call(
        slack_client.conversations_history, channel=lock_channel_id, oldest=oldest
    ):
        for message in result["messages"]:
            try:
                claim = SlotClaim.model_validate_json(message.get("text", ""))
            except ValidationError:
                continue
            claims.append(PostedClaim(claim=claim, ts=message["ts"]))
    return claims


def _winning_claims(claims: list[PostedClaim]) -> dict[int, PostedClaim]:
    winners: dict[int, PostedClaim] = {}
    for posted in sorted(claims, key=lambda posted: Decimal(posted.ts)):
        winners.setdefault(posted.claim.slot, posted)
    return winners


def _release_claim(slack_client: WebClient, lock_channel_id: str, ts: str) -> None:
    """Never raises: an unreleased claim only holds its slot until the TTL."""
    try:
        slack_client.chat_delete(channel=lock_channel_id, ts=ts)
    except SlackApiError as e:
        if slack_error_code(e) != SlackApiErrorCode.MESSAGE_NOT_FOUND:
            print(f"Error releasing Slack pool claim {ts}: {e}")
    except Exception as e:
        print(f"Error releasing Slack pool claim {ts}: {e}")


def _try_claim_slot(
    slack_client: WebClient, lock_channel_id: str, claim: SlotClaim
) -> PostedClaim | None:
    response = slack_client.chat_postMessage(
        channel=lock_channel_id, text=claim.model_dump_json()
    )
    posted = PostedClaim(claim=claim, ts=response["ts"])
    time.sleep(_CLAIM_SETTLE_SECONDS)

    winner = _winning_claims(_read_live_claims(slack_client, lock_channel_id)).get(
        claim.slot
    )
    if winner and winner.ts == posted.ts:
        return posted
    _release_claim(slack_client, lock_channel_id, posted.ts)
    return None


def _claim_free_slot(slack_client: WebClient, lock_channel_id: str) -> PostedClaim:
    run_id = str(uuid4())
    deadline = time.monotonic() + _CLAIM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        busy_slots = _winning_claims(_read_live_claims(slack_client, lock_channel_id))
        # Lowest free slot first keeps the pool as small as the peak concurrency.
        for slot in range(_MAX_POOL_SLOTS):
            if slot in busy_slots:
                continue
            claim = SlotClaim(slot=slot, run_id=run_id)
            if posted := _try_claim_slot(slack_client, lock_channel_id, claim):
                return posted
        time.sleep(_ALL_SLOTS_BUSY_WAIT_SECONDS)
    raise TimeoutError(
        f"No Slack pool slot became free within {_CLAIM_TIMEOUT_SECONDS} seconds"
    )


def _prepare_slot_channels(
    slack_client: WebClient,
    admin_user_id: str,
    channels_by_name: dict[str, ChannelType],
    slot: int,
) -> tuple[ChannelType, ChannelType]:
    public_channel = _get_or_create_channel(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channels_by_name=channels_by_name,
        name=f"{_POOL_CHANNEL_PREFIX}-public-{slot}",
        is_private=False,
    )
    private_channel = _get_or_create_channel(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channels_by_name=channels_by_name,
        name=f"{_POOL_CHANNEL_PREFIX}-private-{slot}",
        is_private=True,
    )
    for channel in (public_channel, private_channel):
        SlackManager.reset_channel(
            slack_client=slack_client, admin_user_id=admin_user_id, channel=channel
        )
    return public_channel, private_channel


@contextmanager
def claim_pool_channels(
    slack_client: WebClient, admin_user_id: str
) -> Generator[tuple[ChannelType, ChannelType], None, None]:
    """Yields an empty (public, private) channel pair that no other run uses."""
    channels_by_name = _index_oldest_by_name(
        SlackManager.list_active_channels(slack_client)
    )
    lock_channel_id = _get_lock_channel(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channels_by_name=channels_by_name,
    )["id"]

    posted = _claim_free_slot(slack_client, lock_channel_id)
    print(f"Claimed Slack pool slot {posted.claim.slot} (claim ts {posted.ts})")
    try:
        yield _prepare_slot_channels(
            slack_client=slack_client,
            admin_user_id=admin_user_id,
            channels_by_name=channels_by_name,
            slot=posted.claim.slot,
        )
    finally:
        _release_claim(slack_client, lock_channel_id, posted.ts)
