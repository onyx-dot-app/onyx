from ee.onyx.external_permissions.dealcloud.access import (
    reads_every_entry,
    reads_nothing,
)
from ee.onyx.external_permissions.dealcloud.group_sync import read_user_groups
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.dealcloud.capability_checks import (
    REQUIRED_FIELDS,
    gateway_from_context,
    probe,
)
from onyx.connectors.dealcloud.config import DealCloudConnectorConfig
from onyx.connectors.dealcloud.models import DealCloudUser, DealCloudUserGroup

_USER_MANAGEMENT_REMEDIATION: str = (
    "Give the API user's group the User Management capability in DealCloud."
)


class _UserGroupsCheck(CapabilityCheck[DealCloudConnectorConfig]):
    """Passes when the groups are readable, whatever they grant. A site where
    no group reads everything is a valid state that the sync must apply, so
    it is an advisory: a failure pauses the connector, and its syncs with it."""

    config_class = DealCloudConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner reads the groups once.
            check_id="dealcloud_user_groups",
            display_name="User groups and what they read are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation=_USER_MANAGEMENT_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        groups: list[DealCloudUserGroup] = probe(
            lambda: read_user_groups(gateway_from_context(context)),
            "The user groups could not be read.",
        )
        advisories: list[CheckAdvisory] = []
        if not any(reads_every_entry(group) for group in groups):
            advisories.append(
                CheckAdvisory(
                    message=(
                        "No DealCloud user group reads all data of every object, "
                        "so no Onyx user will see the DealCloud documents."
                    )
                )
            )
        # Group names are source data, so only their number is reported.
        narrowed: int = sum(
            1
            for group in groups
            if not reads_every_entry(group) and not reads_nothing(group)
        )
        if narrowed:
            advisories.append(
                CheckAdvisory(
                    message=(
                        f"{narrowed} DealCloud user groups read only part of "
                        "the data. Their members see no DealCloud documents "
                        "in Onyx unless another group gives them all data."
                    )
                )
            )
        return CheckOutput(advisories=advisories) if advisories else None


class _UserEmailsCheck(CapabilityCheck[DealCloudConnectorConfig]):
    config_class = DealCloudConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="dealcloud_user_emails",
            display_name="Users' emails are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation="Check that the API user's group can read the site's users.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        users: list[DealCloudUser] = probe(
            gateway_from_context(context).list_active_users,
            "The site's users could not be listed.",
        )
        if any(user.email for user in users):
            return None
        # Not a failure: the sync must run to empty every group, which hides
        # the documents.
        return CheckOutput(
            advisories=[
                CheckAdvisory(
                    message=(
                        "DealCloud listed no active user with an email, so no "
                        "Onyx user can be matched and none will see the "
                        "DealCloud documents."
                    )
                )
            ]
        )


def build_dealcloud_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_UserGroupsCheck(CredentialCapability.DOC_PERMISSION_SYNC)]


def build_dealcloud_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _UserGroupsCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _UserEmailsCheck(),
    ]
