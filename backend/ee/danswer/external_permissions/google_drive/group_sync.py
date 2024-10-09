from collections.abc import Iterator
from typing import Any

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from sqlalchemy.orm import Session

from danswer.connectors.cross_connector_utils.retry_wrapper import retry_builder
from danswer.connectors.google_drive.connector_auth import (
    get_google_drive_creds,
)
from danswer.connectors.google_drive.constants import FETCH_GROUPS_SCOPES
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup
from ee.danswer.db.external_perm import replace_user__ext_group_for_cc_pair__no_commit

logger = setup_logger()


# Google Drive APIs are quite flakey and may 500 for an
# extended period of time. Trying to combat here by adding a very
# long retry period (~20 minutes of trying every minute)
add_retries = retry_builder(tries=5, delay=5, max_delay=30)


def _fetch_groups_paginated(
    google_drive_creds: ServiceAccountCredentials | OAuthCredentials,
    identity_source: str | None = None,
    customer_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    # Note that Google Drive does not use of update the user_cache as the user email
    # comes directly with the call to fetch the groups, therefore this is not a valid
    # place to save on requests
    if identity_source is None and customer_id is None:
        raise ValueError(
            "Either identity_source or customer_id must be provided to fetch groups"
        )

    cloud_identity_service = build(
        "cloudidentity", "v1", credentials=google_drive_creds
    )
    parent = (
        f"identitysources/{identity_source}"
        if identity_source
        else f"customers/{customer_id}"
    )

    while True:
        try:
            groups_resp: dict[str, Any] = add_retries(
                lambda: (cloud_identity_service.groups().list(parent=parent).execute())
            )()
            for group in groups_resp.get("groups", []):
                yield group

            next_token = groups_resp.get("nextPageToken")
            if not next_token:
                break
        except HttpError as e:
            if e.resp.status == 404 or e.resp.status == 403:
                break
            logger.error(f"Error fetching groups: {e}")
            raise


def _fetch_group_members_paginated(
    google_drive_creds: ServiceAccountCredentials | OAuthCredentials,
    group_name: str,
) -> Iterator[dict[str, Any]]:
    cloud_identity_service = build(
        "cloudidentity", "v1", credentials=google_drive_creds
    )
    next_token = None
    while True:
        try:
            membership_info = add_retries(
                lambda: (
                    cloud_identity_service.groups()
                    .memberships()
                    .searchTransitiveMemberships(
                        parent=group_name, pageToken=next_token
                    )
                    .execute()
                )
            )()

            for member in membership_info.get("memberships", []):
                yield member

            next_token = membership_info.get("nextPageToken")
            if not next_token:
                break
        except HttpError as e:
            if e.resp.status == 404 or e.resp.status == 403:
                break
            logger.error(f"Error fetching group members: {e}")
            raise


def gdrive_group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    sync_details = cc_pair.auto_sync_options
    if sync_details is None:
        logger.error("Sync details not found for Google Drive")
        raise ValueError("Sync details not found for Google Drive")

    google_drive_creds, _ = get_google_drive_creds(
        cc_pair.credential.credential_json,
        scopes=FETCH_GROUPS_SCOPES,
    )

    danswer_groups: list[ExternalUserGroup] = []
    for group in _fetch_groups_paginated(
        google_drive_creds,
        identity_source=sync_details.get("identity_source"),
        customer_id=sync_details.get("customer_id"),
    ):
        # The id is the group email
        group_email = group["groupKey"]["id"]

        group_member_emails: list[str] = []
        for member in _fetch_group_members_paginated(google_drive_creds, group["name"]):
            member_keys = member["preferredMemberKey"]
            member_emails = [member_key["id"] for member_key in member_keys]
            for member_email in member_emails:
                group_member_emails.append(member_email)

        group_members = batch_add_non_web_user_if_not_exists__no_commit(
            db_session=db_session, emails=group_member_emails
        )
        if group_members:
            danswer_groups.append(
                ExternalUserGroup(
                    id=group_email, user_ids=[user.id for user in group_members]
                )
            )

    replace_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        group_defs=danswer_groups,
        source=cc_pair.connector.source,
    )
