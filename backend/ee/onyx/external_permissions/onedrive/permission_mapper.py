from onyx.access.models import ExternalAccess
from onyx.connectors.onedrive.access import prefix_onedrive_external_groups
from onyx.connectors.onedrive.models import (
    GraphLinkScope,
    GraphSharePointIdentitySet,
    OneDrivePermission,
)

MEMBERSHIP_LOGIN_PREFIX = "i:0#.f|membership|"


def _check_principal_limit(user_emails: set[str], group_ids: set[str]) -> None:
    if len(user_emails) + len(group_ids) > ExternalAccess.MAX_NUM_ENTRIES:
        raise ValueError("OneDrive item exceeds the external access entry limit.")


def _user_email(identity_set: GraphSharePointIdentitySet) -> str | None:
    for identity in (identity_set.user, identity_set.site_user):
        if identity and (email := identity.email or identity.user_principal_name):
            return email.lower()
    return None


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


def map_onedrive_permissions(
    permissions: list[OneDrivePermission],
    owner_email: str,
    treat_organization_link_as_public: bool,
    add_prefix: bool,
) -> ExternalAccess:
    user_emails: set[str] = {owner_email.lower()}
    group_ids: set[str] = set()
    is_public: bool = False

    for permission in permissions:
        if permission.link is not None:
            if permission.link.scope == GraphLinkScope.ANONYMOUS:
                is_public = True
            elif (
                permission.link.scope == GraphLinkScope.ORGANIZATION
                and treat_organization_link_as_public
            ):
                is_public = True

        identity_sets = list(permission.granted_to_identities_v2)
        if permission.granted_to_v2:
            identity_sets.append(permission.granted_to_v2)
        for identity_set in identity_sets:
            email: str | None = _user_email(identity_set) or _site_user_login_email(
                identity_set
            )
            if email:
                user_emails.add(email)
            group_id: str | None = identity_set.group.id if identity_set.group else None
            if group_id:
                group_ids.add(group_id)
            _check_principal_limit(user_emails, group_ids)

    access = ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=is_public,
    )
    return prefix_onedrive_external_groups(access) if add_prefix else access
