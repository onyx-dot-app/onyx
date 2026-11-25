"""The groups the doc sync names: every security group of the domain with its
users, nested groups included, the domain-everyone group that stands for
Everyone, Authenticated Users and Domain Users, and the exclusion groups the
cc-pair's stored access names. Group ids are bare: the source prefix is added
when the groups are stored."""

import time
from collections.abc import Generator

from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    fetch_referenced_external_group_ids_for_cc_pair,
)
from ee.onyx.external_permissions.microsoft_utils.exclusion_groups import (
    exclusion_group_members,
)
from ee.onyx.external_permissions.microsoft_utils.principal_sets import user_emails
from ee.onyx.external_permissions.smb.connector import smb_connector
from ee.onyx.external_permissions.smb.directory import ActiveDirectory
from ee.onyx.external_permissions.smb.exclusion_groups import (
    EXCLUSION_GROUP_PREFIX,
    parse_exclusion_group_id,
)
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.connectors.smb.connector import SmbConnector
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.sid import normalize_sid
from onyx.connectors.smb.source_operations import SmbSourceOperations
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A group listing still paging past this is a cursor that does not advance.
_MAX_GROUP_PAGES = 100_000


def _group(
    group_id: str, directory: ActiveDirectory, member_ids: frozenset[str]
) -> ExternalUserGroup:
    return ExternalUserGroup(
        id=group_id, user_emails=sorted(user_emails(directory, member_ids))
    )


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise RuntimeError(
            f"Windows file share group sync passed its {PERMISSION_SYNC_TIMEOUT}s "
            "timeout"
        )


def _exclusion_groups(
    directory: ActiveDirectory, exclusion_group_ids: set[str], deadline: float
) -> Generator[ExternalUserGroup, None, None]:
    for group_id in sorted(exclusion_group_ids):
        _check_deadline(deadline)
        term = parse_exclusion_group_id(group_id, directory.domain_sid())
        if term is None:
            logger.warning("Windows file share exclusion group %s is unknown", group_id)
            continue
        yield _group(group_id, directory, exclusion_group_members(term, directory))


def domain_groups(
    ops: SmbSourceOperations,
    email_attribute: EmailAttribute,
    exclusion_group_ids: set[str],
) -> Generator[ExternalUserGroup, None, None]:
    # The caller checks its deadline only per yielded group, and one large
    # group's member pages can take long, so the walk checks it too.
    deadline: float = time.monotonic() + PERMISSION_SYNC_TIMEOUT
    directory = ActiveDirectory(ops, email_attribute)
    yield from _exclusion_groups(directory, exclusion_group_ids, deadline)
    _check_deadline(deadline)
    yield _group(directory.everyone_group_id(), directory, directory.all_users())
    base_dn: str = directory.info().base_dn
    cookie: bytes | None = None
    for _ in range(_MAX_GROUP_PAGES):
        page = ops.list_directory_groups(base_dn=base_dn, cookie=cookie)
        for group in page.groups:
            _check_deadline(deadline)
            sid: str = normalize_sid(group.sid)
            yield _group(sid, directory, directory.group_members(sid))
        cookie = page.cookie
        if cookie is None:
            return
    raise RuntimeError(f"The domain's group listing passed {_MAX_GROUP_PAGES} pages")


def smb_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector: SmbConnector = smb_connector(cc_pair)
    # A service account that lost its directory access would read no members,
    # and the sync would then empty every group without an error.
    connector.validate_perm_sync()
    source_prefix: str = build_ext_group_name_for_onyx("", DocumentSource.SMB)
    with get_session_with_current_tenant() as db_session:
        stored_ids: set[str] = fetch_referenced_external_group_ids_for_cc_pair(
            db_session,
            cc_pair,
            f"{source_prefix}{EXCLUSION_GROUP_PREFIX}:",
        )
    yield from domain_groups(
        connector.ops,
        connector.email_attribute,
        {group_id.removeprefix(source_prefix) for group_id in stored_ids},
    )
