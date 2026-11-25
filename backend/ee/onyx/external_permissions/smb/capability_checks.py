"""Named permission sync checks for a Windows file share. The syncs ask the
domain's Active Directory, over LDAP with TLS, who each SID in an access list
is: the bind, the users with their email addresses, and the group members."""

from ee.onyx.external_permissions.smb.directory import user_email
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
    gateway_from_context,
    probe,
)
from onyx.connectors.smb.config import SmbConnectorConfig
from onyx.connectors.smb.models import (
    DirectoryGroup,
    DirectoryInfo,
    DirectoryUser,
    EmailAttribute,
    SmbCredentials,
)

DIRECTORY_BIND_CHECK_ID = "smb_directory_bind"
DIRECTORY_USERS_CHECK_ID = "smb_directory_users"
DIRECTORY_GROUP_MEMBERS_CHECK_ID = "smb_directory_group_members"

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
        config_fields: frozenset[str] = frozenset(),
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
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


def build_smb_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _DirectoryBindCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _DirectoryUsersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _DirectoryGroupMembersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
    ]
