"""Named permission sync checks for a Windows file share. The syncs ask the
domain's Active Directory, over LDAP with TLS, who each SID in an access list
is: the bind, the users with their email addresses, and the group members."""

from ee.onyx.external_permissions.smb.acl import (
    DaclReaders,
    UnresolvableDenyError,
    dacl_readers,
)
from ee.onyx.external_permissions.smb.directory import ActiveDirectory, user_email
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
)
from onyx.connectors.smb.capability_checks import (
    DOCS_LINK,
    SCOPE_FIELDS,
    SHARE_REQUIRED_FIELDS,
    gateway_from_context,
    probe,
    probe_folders,
)
from onyx.connectors.smb.config import SmbConnectorConfig
from onyx.connectors.smb.connector import join_path
from onyx.connectors.smb.models import (
    DirectoryGroup,
    DirectoryInfo,
    DirectoryUser,
    EmailAttribute,
    SmbCredentials,
)
from onyx.connectors.smb.security_descriptor import SecurityDescriptor
from onyx.connectors.smb.source_operations import SmbAccessDeniedError

DIRECTORY_BIND_CHECK_ID = "smb_directory_bind"
DIRECTORY_USERS_CHECK_ID = "smb_directory_users"
DIRECTORY_GROUP_MEMBERS_CHECK_ID = "smb_directory_group_members"

SHARE_PERMISSIONS_CHECK_ID = "smb_share_permissions_confirmed"
ACCESS_LIST_CHECK_ID = "smb_access_lists"
SID_RESOLUTION_CHECK_ID = "smb_sid_resolution"

# The SID check reads the access lists of this many files and folders.
ACCESS_LIST_SAMPLE_SIZE = 50
USER_SAMPLE_SIZE = 200
_GROUP_SAMPLE_SIZE = 10
# The RID of Domain Users, which every domain has.
_DOMAIN_USERS_RID = 513
_DIRECTORY_REMEDIATION = (
    "Give the service account read access to the domain's users and groups. "
    "A domain user has it by default."
)


def directory_info(context: CapabilityCheckContext) -> DirectoryInfo:
    return probe(
        gateway_from_context(context).get_directory_info,
        "The domain could not be read.",
    )


class _DirectoryCheck(CapabilityCheck[SmbConnectorConfig]):
    config_class = SmbConnectorConfig

    def __init__(
        self,
        *,
        capability: CredentialCapability,
        check_id: str,
        display_name: str,
        remediation: str,
        depends_on: tuple[str, ...] = (DIRECTORY_BIND_CHECK_ID,),
        requires_fields: frozenset[str] = frozenset(),
        config_fields: frozenset[str] = frozenset(),
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
            requires_fields=requires_fields,
            config_fields=config_fields,
            remediation=remediation,
            docs_link=DOCS_LINK,
            depends_on=depends_on,
            fails_when_unreachable=fails_when_unreachable,
        )


class _DirectoryBindCheck(_DirectoryCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner runs it once.
            check_id=DIRECTORY_BIND_CHECK_ID,
            display_name="Sign in to the domain controller",
            remediation=(
                "Set the LDAP host of the credential to a domain controller. "
                "Onyx connects with LDAPS on port 636, or with StartTLS on port "
                "389, and must trust the controller's certificate."
            ),
            depends_on=(),
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        credentials = SmbCredentials.model_validate(context.credential_json)
        if not credentials.ldap_host:
            raise ConnectorValidationError(
                "Permission sync needs the LDAP host of a domain controller in "
                "the credential."
            )
        info: DirectoryInfo = directory_info(context)
        return CheckOutput(
            summary=f"Signed in to {info.base_dn}",
            description=f"Domain SID {info.domain_sid}",
        )


class _DirectoryUsersCheck(_DirectoryCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=DIRECTORY_USERS_CHECK_ID,
            display_name="Domain users have email addresses",
            remediation=(
                "Onyx matches a domain user to an Onyx user by email. Fill the "
                "mail attribute of the users, or set the email attribute to "
                "userPrincipalName if the users sign in to Onyx with it."
            ),
            config_fields=frozenset({"email_attribute"}),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        attribute: EmailAttribute = self.config(context).email_attribute
        base_dn: str = directory_info(context).base_dn
        users: list[DirectoryUser] = probe(
            lambda: (
                gateway.list_directory_users(
                    base_dn=base_dn, page_size=USER_SAMPLE_SIZE
                ).users
            ),
            "The domain's users could not be listed.",
        )
        enabled: list[DirectoryUser] = [user for user in users if user.enabled]
        if not enabled:
            raise InconclusiveValidationError(
                "The domain shows no enabled user, so no email address was read.",
                summary="No users found",
            )
        without: int = sum(1 for user in enabled if user_email(user, attribute) is None)
        if without == len(enabled):
            raise ConnectorValidationError(
                f"None of the first {len(enabled)} enabled domain users has an "
                f"address in {attribute.value}, so no user would get access."
            )
        summary: str = (
            f"{len(enabled) - without} of the first {len(enabled)} enabled users "
            "have an email address"
        )
        if not without:
            return CheckOutput(summary=summary)
        return CheckOutput(
            summary=summary,
            advisories=[
                CheckAdvisory(
                    message=(
                        f"{without} of {len(enabled)} sampled users have no "
                        f"address in {attribute.value}. They get no access "
                        "through permission sync. Service accounts are a normal "
                        "cause."
                    )
                )
            ],
        )


class _DirectoryGroupMembersCheck(_DirectoryCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=DIRECTORY_GROUP_MEMBERS_CHECK_ID,
            display_name="Domain group members are readable",
            remediation=_DIRECTORY_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        info: DirectoryInfo = directory_info(context)
        groups: list[DirectoryGroup] = probe(
            lambda: (
                gateway.list_directory_groups(
                    base_dn=info.base_dn, page_size=_GROUP_SAMPLE_SIZE
                ).groups
            ),
            "The domain's groups could not be listed.",
        )
        if not groups:
            raise ConnectorValidationError(
                "The domain shows no security group to the service account. "
                f"{_DIRECTORY_REMEDIATION}"
            )
        # The doc sync finds each group by the SID an access list names.
        domain_users_sid: str = f"{info.domain_sid}-{_DOMAIN_USERS_RID}"
        group: DirectoryGroup | None = probe(
            lambda: gateway.find_directory_group(
                base_dn=info.base_dn, sid=domain_users_sid
            ),
            "A group could not be found by its SID.",
        )
        if group is None:
            raise ConnectorValidationError(
                f"The domain does not find its Domain Users group by the SID "
                f"{domain_users_sid}. {_DIRECTORY_REMEDIATION}"
            )
        members: list[str] = probe(
            lambda: gateway.list_group_member_sids(base_dn=info.base_dn, group=group),
            "The members of a group could not be read.",
        )
        return CheckOutput(
            summary=f"Read the {len(members)} members of {group.name or group.sid}"
        )


class _SharePermissionsCheck(_DirectoryCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=SHARE_PERMISSIONS_CHECK_ID,
            display_name="The share permissions are confirmed",
            remediation=(
                "Make sure the share permissions grant access to Everyone or "
                "Authenticated Users, so the NTFS permissions alone decide who "
                "reads a file. Then turn on 'Share Permissions Confirmed'."
            ),
            depends_on=(),
            config_fields=frozenset({"share_permissions_confirmed"}),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        if not self.config(context).share_permissions_confirmed:
            raise ConnectorValidationError(
                "Onyx reads the NTFS permissions only. If the share permissions "
                "are narrower, Onyx would show a file to a user the share "
                "refuses. Confirm that the share permissions let in every user "
                "the NTFS permissions let in."
            )
        return CheckOutput(
            summary="An admin confirmed that the NTFS permissions alone decide access"
        )


def _sample_paths(
    context: CapabilityCheckContext, config: SmbConnectorConfig
) -> list[str]:
    """The path prefix, then the first files and folders a walk reaches."""
    gateway = gateway_from_context(context)
    paths: list[str] = [config.path_prefix]
    for folder, entries in probe_folders(gateway, config):
        paths.extend(join_path(folder, entry.name) for entry in entries)
        if len(paths) >= ACCESS_LIST_SAMPLE_SIZE:
            break
    return paths[:ACCESS_LIST_SAMPLE_SIZE]


class _AccessListCheck(_DirectoryCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=ACCESS_LIST_CHECK_ID,
            display_name="Access lists are readable",
            remediation=(
                "Give the service account the Read permissions right on the "
                "files and folders. The NTFS Read permission includes it."
            ),
            depends_on=(),
            requires_fields=SHARE_REQUIRED_FIELDS,
            config_fields=SCOPE_FIELDS,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        config: SmbConnectorConfig = self.config(context)
        paths: list[str] = probe(
            lambda: _sample_paths(context, config), "The share could not be listed."
        )
        probe(
            lambda: gateway.read_security_descriptor(path=paths[0]),
            "The access list of the path prefix could not be read.",
        )
        if len(paths) == 1:
            return CheckOutput(
                summary="Read the access list of the top folder",
                advisories=[
                    CheckAdvisory(
                        message="The folder is empty, so no file's access list was read."
                    )
                ],
            )
        probe(
            lambda: gateway.read_security_descriptor(path=paths[1]),
            f"The access list of {paths[1]} could not be read.",
        )
        return CheckOutput(
            summary="Read the access lists of the top folder and an entry"
        )


class _SidResolutionCheck(_DirectoryCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=SID_RESOLUTION_CHECK_ID,
            display_name="Access lists name domain users and groups",
            remediation=(
                "Onyx cannot see the members of a local group of the file "
                "server, such as BUILTIN\\Users. Grant access to domain groups "
                "or domain users in the NTFS permissions."
            ),
            depends_on=(DIRECTORY_BIND_CHECK_ID, ACCESS_LIST_CHECK_ID),
            requires_fields=SHARE_REQUIRED_FIELDS,
            config_fields=SCOPE_FIELDS | {"email_attribute"},
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        config: SmbConnectorConfig = self.config(context)
        directory = ActiveDirectory(gateway, config.email_attribute)
        paths: list[str] = probe(
            lambda: _sample_paths(context, config), "The share could not be listed."
        )
        read: int = 0
        local_only: list[str] = []
        unresolvable_deny: list[str] = []
        unknown_sids: set[str] = set()
        named_sids: set[str] = set()
        for path in paths:
            try:
                descriptor: SecurityDescriptor = probe(
                    lambda path=path: gateway.read_security_descriptor(path=path),
                    f"The access list of {path} could not be read.",
                )
            except SmbAccessDeniedError:
                continue
            read += 1
            named_sids.update(ace.sid for ace in descriptor.aces)
            try:
                readers: DaclReaders = probe(
                    lambda descriptor=descriptor: dacl_readers(descriptor, directory),
                    "The domain could not be read.",
                )
            except UnresolvableDenyError:
                unresolvable_deny.append(path)
                continue
            unknown_sids.update(readers.unknown_allow_sids)
            if readers.unknown_allow_sids and not readers.principals:
                local_only.append(path)
        if not read:
            raise InconclusiveValidationError(
                "No access list in the sample was readable.",
                summary="No access list read",
            )
        hidden: int = len(local_only) + len(unresolvable_deny)
        if hidden == read:
            raise ConnectorValidationError(
                f"None of the {read} sampled files and folders grants access to "
                "a domain user or group that Onyx can name, so no user would "
                "see them. The access lists name: "
                f"{', '.join(sorted(unknown_sids)) or 'no known principal'}."
            )
        advisories: list[CheckAdvisory] = []
        if unknown_sids:
            advisories.append(
                CheckAdvisory(
                    message=(
                        f"{len(unknown_sids)} of {len(named_sids)} SIDs in the "
                        "sampled access lists are not domain users or groups "
                        f"({', '.join(sorted(unknown_sids)[:5])}). Onyx ignores "
                        "them."
                    )
                )
            )
        if local_only:
            advisories.append(
                CheckAdvisory(
                    message=(
                        f"{len(local_only)} of {read} sampled files and folders "
                        "grant read access only to such principals, e.g. "
                        f"{local_only[0] or 'the top folder'}. No user sees "
                        "them in Onyx."
                    )
                )
            )
        if unresolvable_deny:
            advisories.append(
                CheckAdvisory(
                    message=(
                        f"{len(unresolvable_deny)} of {read} sampled files and "
                        "folders have a deny entry for such a principal, e.g. "
                        f"{unresolvable_deny[0] or 'the top folder'}. They stay "
                        "private."
                    )
                )
            )
        return CheckOutput(
            summary=(
                f"{read - hidden} of {read} sampled access lists resolve to "
                "domain users or groups"
            ),
            advisories=advisories,
        )


def build_smb_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _SharePermissionsCheck(),
        _DirectoryBindCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _DirectoryUsersCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _DirectoryGroupMembersCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _AccessListCheck(),
        _SidResolutionCheck(),
    ]


def build_smb_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _DirectoryBindCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _DirectoryUsersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _DirectoryGroupMembersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
    ]
