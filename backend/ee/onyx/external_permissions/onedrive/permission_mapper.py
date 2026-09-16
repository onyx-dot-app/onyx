from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.onedrive.models import (
    GraphIdentity,
    GraphLinkScope,
    GraphSharePointIdentitySet,
    OneDrivePermission,
)

MEMBERSHIP_LOGIN_PREFIX = "i:0#.f|membership|"


def _check_principal_limit(user_emails: set[str], group_ids: set[str]) -> None:
    if len(user_emails) + len(group_ids) > ExternalAccess.MAX_NUM_ENTRIES:
        raise ValueError("OneDrive item exceeds the external access entry limit.")


def _user_email(identity_set: GraphSharePointIdentitySet) -> str | None:
    user = identity_set.user
    site_user = identity_set.site_user
    email = _identity_email(user) or _identity_email(site_user)
    return email.lower() if email else None


def _identity_email(identity: GraphIdentity | None) -> str | None:
    if identity is None:
        return None
    return identity.email or identity.user_principal_name


def _site_user_login_email(identity_set: GraphSharePointIdentitySet) -> str | None:
    site_user = identity_set.site_user
    if site_user is None:
        return None
    if site_user.login_name is None:
        return None
    normalized = site_user.login_name.lower()
    if not normalized.startswith(MEMBERSHIP_LOGIN_PREFIX):
        return None
    return normalized.removeprefix(MEMBERSHIP_LOGIN_PREFIX)


def _identity_sets(
    permission: OneDrivePermission,
) -> list[GraphSharePointIdentitySet]:
    identities = list(permission.granted_to_identities_v2)
    if permission.granted_to_v2 is not None:
        identities.append(permission.granted_to_v2)
    return identities


def map_onedrive_permissions(
    permissions: list[OneDrivePermission],
    owner_email: str,
    treat_organization_link_as_public: bool,
    add_prefix: bool,
) -> ExternalAccess:
    user_emails = {owner_email.lower()}
    group_ids: set[str] = set()
    is_public = False

    for permission in permissions:
        if permission.link is not None:
            if permission.link.scope == GraphLinkScope.ANONYMOUS:
                is_public = True
            elif (
                permission.link.scope == GraphLinkScope.ORGANIZATION
                and treat_organization_link_as_public
            ):
                is_public = True

        for identity_set in _identity_sets(permission):
            email = _user_email(identity_set) or _site_user_login_email(identity_set)
            if identity_set.user is not None and email:
                user_emails.add(email)
            group_id = identity_set.group.id if identity_set.group else None
            if group_id:
                group_ids.add(
                    build_ext_group_name_for_onyx(group_id, DocumentSource.ONEDRIVE)
                    if add_prefix
                    else group_id
                )
            _check_principal_limit(user_emails, group_ids)

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=is_public,
    )
