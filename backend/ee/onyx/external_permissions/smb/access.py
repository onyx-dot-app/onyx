"""Who may read each file and list each folder of a Windows file share.

Access comes from the NTFS access list alone. The share permissions are not
read: an admin confirms that they let in every user the NTFS permissions let
in (``share_permissions_confirmed``). Nothing is ever public: Everyone,
Authenticated Users and Domain Users become the synced group of the domain's
users. A term with exclusions becomes an exclusion group.
"""

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    ExpansionLimitError,
    ResolvedPrincipals,
    resolve,
)
from ee.onyx.external_permissions.smb.acl import (
    DaclReaders,
    UnresolvableDenyError,
    dacl_readers,
)
from ee.onyx.external_permissions.smb.directory import ActiveDirectory
from ee.onyx.external_permissions.smb.exclusion_groups import exclusion_group_id
from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import SMB_ACL_READ_CONCURRENCY
from onyx.connectors.smb.access import SmbAccessWalker
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.security_descriptor import SecurityDescriptor
from onyx.connectors.smb.source_operations import (
    SmbAccessDeniedError,
    SmbNotFoundError,
    SmbSourceOperations,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


class SmbAccessResolver(SmbAccessWalker):
    def __init__(
        self, ops: SmbSourceOperations, email_attribute: EmailAttribute
    ) -> None:
        self._ops = ops
        self._directory = ActiveDirectory(ops, email_attribute)

    def _read_descriptor(self, path: str) -> SecurityDescriptor | None:
        """None for a path that was deleted during the walk, or whose access
        list the service account may not read. Each other failure raises, so
        a server error fails the sync rather than making files private."""
        try:
            return self._ops.read_security_descriptor(path=path)
        except SmbNotFoundError:
            logger.info("%s was deleted during the walk", path or "\\")
            return None
        except SmbAccessDeniedError:
            logger.warning(
                "%s stays private: the service account may not read its access list",
                path or "\\",
            )
            return None

    def _external_access(
        self, path: str, descriptor: SecurityDescriptor | None
    ) -> ExternalAccess:
        if descriptor is None:
            return ExternalAccess.empty()
        try:
            readers: DaclReaders = dacl_readers(descriptor, self._directory)
            resolved: ResolvedPrincipals = resolve(
                readers.principals, self._directory, ExternalAccess.MAX_NUM_ENTRIES
            )
            group_ids: set[str] = resolved.group_ids | {
                exclusion_group_id(term, self._directory.domain_sid())
                for term in resolved.exclusion_terms
            }
        except (ExpansionLimitError, UnresolvableDenyError) as e:
            logger.error("%s stays private: %s", path or "\\", e)
            return ExternalAccess.empty()
        if resolved.everyone:
            group_ids.add(self._directory.everyone_group_id())
        access = ExternalAccess(
            external_user_emails=resolved.user_emails,
            external_user_group_ids=group_ids,
            is_public=False,
        )
        # The permission writer skips an oversized entry and keeps the old
        # access, which can be wider than the new one.
        if access.num_entries > ExternalAccess.MAX_NUM_ENTRIES:
            logger.error(
                "%s stays private: %s entries is over %s",
                path or "\\",
                access.num_entries,
                ExternalAccess.MAX_NUM_ENTRIES,
            )
            return ExternalAccess.empty()
        return access

    def paths_access(self, paths: list[str]) -> dict[str, ExternalAccess]:
        # The reads run in parallel. The directory lookups do not: its caches
        # are plain dicts.
        descriptors: list[SecurityDescriptor | None] = run_functions_tuples_in_parallel(
            [(self._read_descriptor, (path,)) for path in paths],
            max_workers=SMB_ACL_READ_CONCURRENCY,
        )
        return {
            path: self._external_access(path, descriptor)
            for path, descriptor in zip(paths, descriptors, strict=True)
        }


def build_access_walker(
    ops: SmbSourceOperations, email_attribute: EmailAttribute
) -> SmbAccessWalker:
    return SmbAccessResolver(ops, email_attribute)
