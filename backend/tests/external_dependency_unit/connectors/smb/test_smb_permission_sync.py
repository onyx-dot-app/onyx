"""Permission sync against a live share and its Active Directory domain: the
NTFS access list of each file, as the readers Onyx stores for it."""

import pytest

from ee.onyx.connectors.perm_sync_valid import smb_check_context
from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    everyone_term,
    group_term,
)
from ee.onyx.external_permissions.smb.capability_checks import (
    build_smb_doc_permission_sync_checks,
    build_smb_group_sync_checks,
)
from ee.onyx.external_permissions.smb.exclusion_groups import exclusion_group_id
from ee.onyx.external_permissions.smb.group_sync import domain_groups
from onyx.access.models import ExternalAccess
from onyx.connectors.models import SlimDocument
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.security_descriptor import Ace
from onyx.connectors.smb.sid import normalize_sid
from onyx.connectors.smb.source_operations import SmbSourceOperations
from tests.external_dependency_unit.connectors.smb.conftest import (
    HOST,
    LDAP_PORT,
    MAIL_DOMAIN,
    SERVICE_ACCOUNT,
    SHARE,
    ConnectorFactory,
    credential_json,
)
from tests.external_dependency_unit.connectors.smb.smb_share_admin import (
    ShareAdmin,
    allow,
    deny,
)

pytestmark = pytest.mark.usefixtures("enable_ee")

ROOT_ID = f"smb://{HOST.lower()}/{SHARE}"
EVERYONE = "S-1-1-0"
AUTHENTICATED_USERS = "S-1-5-11"
BUILTIN_USERS = "S-1-5-32-545"


def _email(name: str) -> str:
    return f"{name}@{MAIL_DOMAIN}"


class Domain:
    """The SIDs of the seeded users and groups, read from the directory."""

    def __init__(self, ops: SmbSourceOperations) -> None:
        info = ops.get_directory_info()
        self.sid = normalize_sid(info.domain_sid)
        self.users: dict[str, str] = {}
        cookie: bytes | None = None
        while True:
            page = ops.list_directory_users(base_dn=info.base_dn, cookie=cookie)
            for user in page.users:
                address = user.mail or user.user_principal_name
                if address:
                    self.users[address.split("@")[0]] = normalize_sid(user.sid)
            cookie = page.cookie
            if cookie is None:
                break
        self.groups: dict[str, str] = {
            group.name: normalize_sid(group.sid)
            for group in ops.list_directory_groups(base_dn=info.base_dn).groups
            if group.name
        }

    @property
    def everyone_group(self) -> str:
        return f"ad_domain_everyone:{self.sid}"


@pytest.fixture
def domain(ops: SmbSourceOperations) -> Domain:
    return Domain(ops)


def _service_email(domain: Domain, connector_factory: ConnectorFactory) -> str:
    """The service account has no mail, so Onyx knows it by its user principal
    name."""
    ops = connector_factory().ops
    info = ops.get_directory_info()
    cookie: bytes | None = None
    while True:
        page = ops.list_directory_users(base_dn=info.base_dn, cookie=cookie)
        for user in page.users:
            if normalize_sid(user.sid) == domain.users[SERVICE_ACCOUNT]:
                assert user.user_principal_name is not None
                return user.user_principal_name.lower()
        cookie = page.cookie
        assert cookie is not None, "The service account is in the directory."


def _access(
    connector_factory: ConnectorFactory, workspace: str
) -> dict[str, ExternalAccess]:
    access: dict[str, ExternalAccess] = {}
    for batch in connector_factory(workspace).retrieve_all_slim_docs_perm_sync():
        for item in batch:
            assert item.external_access is not None
            assert not item.external_access.is_public
            if isinstance(item, SlimDocument):
                name = item.id.removeprefix(f"{ROOT_ID}/{workspace}/")
                access[name] = item.external_access
    return access


def _readers(access: ExternalAccess) -> tuple[set[str], set[str]]:
    return access.external_user_emails, access.external_user_group_ids


def test_each_access_list_becomes_the_readers_windows_would_let_in(
    share_admin: ShareAdmin,
    workspace: str,
    connector_factory: ConnectorFactory,
    domain: Domain,
) -> None:
    alice, bob, carol, dave = (
        domain.users[name] for name in ("alice", "bob", "carol", "dave")
    )
    engineering = domain.groups["Engineering"]
    restricted = domain.groups["Restricted"]
    domain_users = domain.groups["Domain Users"]
    # The service account reads every file it indexes, and a file's access
    # list with it. Its entry is first, so no deny entry stops it.
    service = domain.users[SERVICE_ACCOUNT]
    service_email = _service_email(domain, connector_factory)
    lists: dict[str, list[Ace]] = {
        "user.txt": [allow(alice)],
        "group.txt": [allow(engineering)],
        "disabled.txt": [allow(dave)],
        "everyone.txt": [allow(EVERYONE)],
        "authenticated.txt": [allow(AUTHENTICATED_USERS)],
        "domain_users.txt": [allow(domain_users)],
        "local_group.txt": [allow(BUILTIN_USERS)],
        "deny_user.txt": [deny(bob), allow(engineering)],
        "deny_group.txt": [deny(restricted), allow(AUTHENTICATED_USERS)],
        "deny_after_allow.txt": [allow(engineering), deny(bob), allow(carol)],
        "deny_everyone.txt": [deny(EVERYONE), allow(alice)],
        "deny_local_group.txt": [deny(BUILTIN_USERS), allow(alice)],
        "nobody.txt": [],
    }
    for name, aces in lists.items():
        share_admin.write(f"{workspace}/{name}", name)
        share_admin.set_dacl(f"{workspace}/{name}", [allow(service), *aces])

    access = _access(connector_factory, workspace)

    only_service: tuple[set[str], set[str]] = ({service_email}, set())
    # The whole domain holds the service account too.
    whole_domain: tuple[set[str], set[str]] = (set(), {domain.everyone_group})
    expected: dict[str, tuple[set[str], set[str]]] = {
        "user.txt": ({service_email, _email("alice")}, set()),
        "group.txt": ({service_email}, {engineering}),
        "disabled.txt": only_service,
        "everyone.txt": whole_domain,
        "authenticated.txt": whole_domain,
        "domain_users.txt": whole_domain,
        # Onyx cannot name the members of a local group of the file server.
        "local_group.txt": only_service,
        "deny_user.txt": (
            {service_email},
            {exclusion_group_id(group_term(engineering, [bob]), domain.sid)},
        ),
        "deny_group.txt": (
            {service_email},
            {
                exclusion_group_id(
                    everyone_term(excluded_groups=[restricted]), domain.sid
                )
            },
        ),
        # Windows stops at the first entry that decides: bob is let in
        # through Engineering before his deny entry.
        "deny_after_allow.txt": ({service_email, _email("carol")}, {engineering}),
        "deny_everyone.txt": only_service,
        # A deny entry for a principal Onyx cannot name could stop anyone.
        "deny_local_group.txt": (set(), set()),
        "nobody.txt": only_service,
    }
    assert {name: _readers(item) for name, item in access.items()} == expected


def test_a_file_whose_access_list_the_account_may_not_read_stays_private(
    share_admin: ShareAdmin,
    workspace: str,
    connector_factory: ConnectorFactory,
    domain: Domain,
) -> None:
    share_admin.write(f"{workspace}/hidden.txt", "hidden")
    share_admin.set_dacl(f"{workspace}/hidden.txt", [allow(domain.users["alice"])])

    access = _access(connector_factory, workspace)

    assert access == {"hidden.txt": ExternalAccess.empty()}


def test_group_sync_resolves_nested_groups_and_exclusion_groups(
    ops: SmbSourceOperations, domain: Domain
) -> None:
    engineering = domain.groups["Engineering"]
    restricted = domain.groups["Restricted"]
    engineering_without_bob = exclusion_group_id(
        group_term(engineering, [domain.users["bob"]]), domain.sid
    )
    domain_without_restricted = exclusion_group_id(
        everyone_term(excluded_groups=[restricted]), domain.sid
    )

    groups = {
        group.id: set(group.user_emails)
        for group in domain_groups(
            ops,
            EmailAttribute.MAIL,
            {engineering_without_bob, domain_without_restricted},
        )
    }

    # alice is a member through the nested Backend group.
    assert groups[engineering] == {_email("alice"), _email("bob")}
    # dave is disabled.
    assert groups[restricted] == {_email("carol")}
    assert groups[engineering_without_bob] == {_email("alice")}
    everyone = groups[domain.everyone_group]
    assert {_email("alice"), _email("bob"), _email("carol")} <= everyone
    assert _email("dave") not in everyone
    # The service account has no mail, so its user principal name is used.
    assert any(email.startswith(f"{SERVICE_ACCOUNT}@") for email in everyone)
    assert groups[domain_without_restricted] == everyone - {_email("carol")}


def test_every_permission_sync_check_passes_for_the_service_account(
    share_admin: ShareAdmin,
    workspace: str,
    connector_factory: ConnectorFactory,
    domain: Domain,
) -> None:
    share_admin.write(f"{workspace}/plan.txt", "plan")
    share_admin.set_dacl(
        f"{workspace}/plan.txt",
        [allow(domain.users[SERVICE_ACCOUNT]), allow(domain.groups["Engineering"])],
    )
    connector = connector_factory(workspace)

    connector.validate_perm_sync()
    for check in build_smb_doc_permission_sync_checks() + build_smb_group_sync_checks():
        check.run(smb_check_context(connector))


def test_the_directory_also_answers_over_starttls(
    connector_factory: ConnectorFactory,
) -> None:
    connector = connector_factory(
        credentials=credential_json(ldap_port=LDAP_PORT, ldap_tls="starttls")
    )

    assert connector.ops.get_directory_info().domain_sid.startswith("S-1-5-21-")
