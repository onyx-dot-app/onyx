from collections import defaultdict
from enum import StrEnum

from jira import JIRA
from jira.resources import PermissionScheme
from pydantic import ValidationError

from ee.onyx.external_permissions.jira.models import Holder
from ee.onyx.external_permissions.jira.models import Permission
from ee.onyx.external_permissions.jira.models import User
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION
from onyx.utils.logger import setup_logger

HolderMap = dict[str, list[Holder]]


logger = setup_logger()

BROWSE_PROJECTS_PERMISSION = "BROWSE_PROJECTS"
HOLDER_TYPE_ANYONE = "anyone"
HOLDER_TYPE_APPLICATION_ROLE = "applicationRole"
HOLDER_TYPE_USER = "user"
HOLDER_TYPE_PROJECT_ROLE = "projectRole"
HOLDER_TYPE_GROUP = "group"

SUPPORTED_STATIC_HOLDER_TYPES = {
    HOLDER_TYPE_ANYONE,
    HOLDER_TYPE_APPLICATION_ROLE,
    HOLDER_TYPE_USER,
    HOLDER_TYPE_PROJECT_ROLE,
    HOLDER_TYPE_GROUP,
}

# Jira DC/Server returns project-role actors flat with this `type` discriminator;
# Jira Cloud v3 instead wraps them in nested `actorGroup` / `actorUser` objects.
ATLASSIAN_GROUP_ROLE_ACTOR_TYPE = "atlassian-group-role-actor"
ATLASSIAN_USER_ROLE_ACTOR_TYPE = "atlassian-user-role-actor"


class _RoleActorCategory(StrEnum):
    GROUP = "group"
    USER = "user"
    UNSUPPORTED = "unsupported"


def _get_role_id(holder: Holder) -> str | None:
    return holder.get("value") or holder.get("parameter")


# Jira SDK resources expose fields as attributes, raw dicts, or nested raw payloads
# depending on Jira version and endpoint.
def _get_obj_value(obj: object, field: str) -> object | None:
    if isinstance(obj, dict):
        return obj.get(field)  # ty: ignore[invalid-argument-type]
    return getattr(obj, field, None)


def _get_raw_value(obj: object, field: str) -> object | None:
    raw = _get_obj_value(obj, "raw")
    return _get_obj_value(raw, field)


def _get_first_str_value(obj: object, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _get_obj_value(obj, field) or _get_raw_value(obj, field)
        if isinstance(value, str) and value:
            return value
    return None


def _is_cloud_client(jira_client: JIRA) -> bool:
    try:
        return jira_client._options["rest_api_version"] == JIRA_CLOUD_API_VERSION
    except Exception:
        return False


def _get_holder_counts(holder_map: HolderMap) -> dict[str, int]:
    return {
        holder_type: len(holders) for holder_type, holders in sorted(holder_map.items())
    }


def _get_unsupported_holder_counts(holder_map: HolderMap) -> dict[str, int]:
    return {
        holder_type: count
        for holder_type, count in _get_holder_counts(holder_map).items()
        if holder_type not in SUPPORTED_STATIC_HOLDER_TYPES
    }


def _build_holder_map(permissions: list[dict]) -> dict[str, list[Holder]]:
    """
    A "Holder" in JIRA is a person / entity who "holds" the corresponding permission.
    It can have different types. They can be one of (but not limited to):
        - user (an explicitly whitelisted user)
        - projectRole (for project level "roles")
        - reporter (the reporter of an issue)

    A "Holder" usually has following structure:
        - `{ "type": "user", "value": "$USER_ID", "user": { .. }, .. }`
        - `{ "type": "projectRole", "value": "$PROJECT_ID", ..  }`

    When we fetch the PermissionSchema from JIRA, we retrieve a list of "Holder"s.
    The list of "Holder"s can have multiple "Holder"s of the same type in the list (e.g., you can have two `"type": "user"`s in
    there, each corresponding to a different user).
    This function constructs a map of "Holder" types to a list of the "Holder"s which contained that type.

    Returns:
        A dict from the "Holder" type to the actual "Holder" instance.

    Example:
        ```
        {
            "user": [
                { "type": "user", "value": "10000", "user": { .. }, .. },
                { "type": "user", "value": "10001", "user": { .. }, .. },
            ],
            "projectRole": [
                { "type": "projectRole", "value": "10010", ..  },
                { "type": "projectRole", "value": "10011", ..  },
            ],
            "applicationRole": [
                { "type": "applicationRole" },
            ],
            ..
        }
        ```
    """

    holder_map: defaultdict[str, list[Holder]] = defaultdict(list)

    for raw_perm in permissions:
        if not hasattr(raw_perm, "raw"):
            logger.warning(
                "Expected a 'raw' field, but none was found: raw_perm=%r", raw_perm
            )
            continue

        permission = Permission(**raw_perm.raw)  # ty: ignore[invalid-argument-type]

        # We only care about ability to browse through projects + issues (not other permissions such as read/write).
        if permission.permission != BROWSE_PROJECTS_PERMISSION:
            continue

        # In order to associate this permission to some Atlassian entity, we need the "Holder".
        # If this doesn't exist, then we cannot associate this permission to anyone; just skip.
        if not permission.holder:
            logger.warning(
                "Expected to find a permission holder, but none was found: permission=%r",
                permission,
            )
            continue

        type = permission.holder.get("type")
        if not type:
            logger.warning(
                "Expected to find the type of permission holder, but none was found: permission=%r",
                permission,
            )
            continue

        holder_map[type].append(permission.holder)

    return holder_map


def _get_user_email_from_holder(
    jira_project: str,
    user_holder: Holder,
) -> str | None:
    if "user" not in user_holder:
        logger.warning(
            "Jira project %s user holder has no expanded user object; holder=%s",
            jira_project,
            user_holder,
        )
        return None

    raw_user_dict = user_holder["user"]

    try:
        user_model = User.model_validate(raw_user_dict)
        return user_model.email_address
    except ValidationError:
        email = _get_first_str_value(raw_user_dict, ("emailAddress", "email_address"))
        if email:
            logger.info(
                "Jira project %s user holder used fallback email parsing for expanded "
                "user with fields=%s",
                jira_project,
                sorted(raw_user_dict.keys()) if isinstance(raw_user_dict, dict) else [],
            )
            return email

        logger.error(
            "Jira project %s user holder expanded user failed validation and had no "
            "fallback email; raw_user_dict=%r",
            jira_project,
            raw_user_dict,
        )
        return None


def _get_user_emails(jira_project: str, user_holders: list[Holder]) -> list[str]:
    emails = []
    missing_email_count = 0

    for user_holder in user_holders:
        email = _get_user_email_from_holder(jira_project, user_holder)
        if not email:
            missing_email_count += 1
            continue
        emails.append(email)

    if user_holders and not emails:
        logger.warning(
            "Jira project %s resolved zero emails from direct user holders; "
            "user_holder_count=%s missing_email_count=%s",
            jira_project,
            len(user_holders),
            missing_email_count,
        )

    return emails


def _describe_actor(actor: object) -> object:
    """Render a project-role actor for triage logs. `jira.resources.PropertyHolder`
    inherits object's default repr (only the memory address); dump its populated
    attributes one level deep so unsupported/empty-name cases are debuggable."""
    if isinstance(actor, dict):
        return actor
    if not hasattr(actor, "__dict__"):
        return repr(actor)
    return {
        k: (
            {ik: iv for ik, iv in vars(v).items() if not ik.startswith("_")}
            if hasattr(v, "__dict__")
            else v
        )
        for k, v in vars(actor).items()
        if not k.startswith("_")
    }


def _classify_role_actor(actor: object) -> _RoleActorCategory:
    """Categorize a project-role actor across Cloud v3's nested
    `actorGroup`/`actorUser` shape and DC/Server's flat `type=atlassian-*-role-actor`
    shape."""
    if (
        _get_obj_value(actor, "actorGroup") is not None
        or _get_raw_value(actor, "actorGroup") is not None
    ):
        return _RoleActorCategory.GROUP
    if (
        _get_obj_value(actor, "actorUser") is not None
        or _get_raw_value(actor, "actorUser") is not None
    ):
        return _RoleActorCategory.USER

    actor_type = _get_first_str_value(actor, ("type",))
    if actor_type == ATLASSIAN_GROUP_ROLE_ACTOR_TYPE:
        return _RoleActorCategory.GROUP
    if actor_type == ATLASSIAN_USER_ROLE_ACTOR_TYPE:
        return _RoleActorCategory.USER

    return _RoleActorCategory.UNSUPPORTED


def _get_actor_group_name(actor: object) -> str | None:
    for actor_group in [
        _get_obj_value(actor, "actorGroup"),
        _get_raw_value(actor, "actorGroup"),
    ]:
        if actor_group is None:
            continue
        group_name = _get_first_str_value(actor_group, ("name", "displayName"))
        if group_name:
            return group_name

    return _get_first_str_value(actor, ("parameter", "name", "displayName"))


def _get_user_lookup_id(jira_client: JIRA, actor_user: object) -> str | None:
    if _is_cloud_client(jira_client):
        return _get_first_str_value(actor_user, ("accountId", "name", "key"))
    return _get_first_str_value(actor_user, ("name", "key", "accountId"))


def _get_actor_user_email(
    jira_client: JIRA,
    jira_project: str,
    role_id: str,
    actor_user: object,
) -> str | None:
    embedded_email = _get_first_str_value(actor_user, ("emailAddress", "email_address"))
    if embedded_email:
        return embedded_email

    user_lookup_id = _get_user_lookup_id(jira_client, actor_user)
    if not user_lookup_id:
        logger.error(
            "Jira project %s project role %s actorUser has no usable user identifier; "
            "actor_user=%s",
            jira_project,
            role_id,
            actor_user,
        )
        return None

    user = jira_client.user(id=user_lookup_id)
    account_type = getattr(user, "accountType", None)
    if account_type is not None and account_type != "atlassian":
        logger.info(
            "Skipping Jira project %s project role %s user %s because it is not an "
            "atlassian user",
            jira_project,
            role_id,
            user_lookup_id,
        )
        return None

    email = getattr(user, "emailAddress", None)
    if email:
        return email

    logger.warning(
        "Jira project %s project role %s user email was not available; "
        "user_lookup_id=%s",
        jira_project,
        role_id,
        user_lookup_id,
    )
    return None


def _get_user_emails_and_groups_from_project_roles(
    jira_client: JIRA,
    jira_project: str,
    project_role_holders: list[Holder],
) -> tuple[list[str], list[str]]:
    """
    Get user emails and group names from project roles.
    Returns a tuple of (emails, group_names).
    """
    # Get role IDs - Cloud uses "value", Data Center uses "parameter"
    role_ids = []
    missing_role_id_count = 0
    for holder in project_role_holders:
        role_id = _get_role_id(holder)
        if role_id:
            role_ids.append(role_id)
        else:
            missing_role_id_count += 1
            logger.warning(
                "Jira project %s projectRole holder has no value or parameter: %s",
                jira_project,
                holder,
            )

    if not role_ids:
        logger.warning(
            "Jira project %s has %s projectRole holders but none had a usable role id; "
            "project-role groups will be empty",
            jira_project,
            len(project_role_holders),
        )

    roles = [
        jira_client.project_role(project=jira_project, id=role_id)
        for role_id in role_ids
    ]

    emails = []
    groups = []
    actor_group_seen_count = 0
    actor_group_missing_name_count = 0
    actor_user_seen_count = 0
    roles_without_actors_count = 0
    unsupported_actor_count = 0

    for role_id, role in zip(role_ids, roles, strict=True):
        if not hasattr(role, "actors"):
            roles_without_actors_count += 1
            logger.warning(
                "Jira project %s project role %s has no actors attribute; "
                "this role cannot contribute users or groups",
                jira_project,
                role_id,
            )
            continue

        for actor in role.actors:
            category = _classify_role_actor(actor)
            logger.debug(
                "Jira project %s project role %s actor classified; "
                "category=%s actor=%s",
                jira_project,
                role_id,
                category.value,
                _describe_actor(actor),
            )

            if category is _RoleActorCategory.GROUP:
                actor_group_seen_count += 1
                group_name = _get_actor_group_name(actor)
                if group_name:
                    groups.append(group_name)
                else:
                    actor_group_missing_name_count += 1
                    logger.warning(
                        "Jira project %s project role %s has group actor with no "
                        "name/displayName; actor=%s",
                        jira_project,
                        role_id,
                        actor,
                    )
                continue

            if category is _RoleActorCategory.USER:
                actor_user_seen_count += 1
                # Prefer Cloud's nested `actorUser` (keeps accountId lookup);
                # fall back to the actor itself for DC's flat shape.
                actor_user = (
                    _get_obj_value(actor, "actorUser")
                    or _get_raw_value(actor, "actorUser")
                    or actor
                )
                email = _get_actor_user_email(
                    jira_client=jira_client,
                    jira_project=jira_project,
                    role_id=role_id,
                    actor_user=actor_user,
                )
                if email:
                    emails.append(email)
                continue

            unsupported_actor_count += 1
            logger.warning(
                "Jira project %s project role %s has unsupported actor shape; actor=%s",
                jira_project,
                role_id,
                actor,
            )

    if project_role_holders and not groups:
        logger.warning(
            "Jira project %s resolved zero groups from projectRole holders; "
            "project_role_holder_count=%s valid_role_id_count=%s "
            "missing_role_id_count=%s roles_fetched=%s roles_without_actors=%s "
            "actor_group_seen=%s actor_group_missing_name=%s actor_user_seen=%s "
            "user_email_count=%s unsupported_actor_count=%s",
            jira_project,
            len(project_role_holders),
            len(role_ids),
            missing_role_id_count,
            len(roles),
            roles_without_actors_count,
            actor_group_seen_count,
            actor_group_missing_name_count,
            actor_user_seen_count,
            len(emails),
            unsupported_actor_count,
        )

    return emails, groups


def _build_external_access_from_holder_map(
    jira_client: JIRA, jira_project: str, holder_map: HolderMap
) -> ExternalAccess:
    """
    Build ExternalAccess from the holder map.

    Holder types handled:
        - "anyone": Public project, anyone can access
        - "applicationRole": All users with a Jira license can access (treated as public)
        - "user": Specific users with access
        - "projectRole": Project roles containing users and/or groups
        - "group": Groups directly assigned in the permission scheme
    """
    holder_counts = _get_holder_counts(holder_map)
    unsupported_holder_counts = _get_unsupported_holder_counts(holder_map)
    if not holder_map:
        logger.warning(
            "Jira project %s has no usable %s permission holders; "
            "external access will resolve to empty private access",
            jira_project,
            BROWSE_PROJECTS_PERMISSION,
        )
    if unsupported_holder_counts:
        logger.warning(
            "Jira project %s has unsupported %s holder types that do not map to "
            "static Onyx ACLs; unsupported_holder_counts=%s all_holder_counts=%s",
            jira_project,
            BROWSE_PROJECTS_PERMISSION,
            unsupported_holder_counts,
            holder_counts,
        )

    # Public access - anyone can view
    if HOLDER_TYPE_ANYONE in holder_map:
        logger.info(
            "Jira project %s has anyone holder; resolving as public external access "
            "with empty explicit groups",
            jira_project,
        )
        return ExternalAccess(
            external_user_emails=set(), external_user_group_ids=set(), is_public=True
        )

    # applicationRole means all users with a Jira license can access - treat as public
    if HOLDER_TYPE_APPLICATION_ROLE in holder_map:
        logger.info(
            "Jira project %s has applicationRole holder; resolving as public external "
            "access with empty explicit groups",
            jira_project,
        )
        return ExternalAccess(
            external_user_emails=set(), external_user_group_ids=set(), is_public=True
        )

    # Get emails from explicit user holders
    user_emails = (
        _get_user_emails(
            jira_project=jira_project,
            user_holders=holder_map[HOLDER_TYPE_USER],
        )
        if HOLDER_TYPE_USER in holder_map
        else []
    )

    # Get emails and groups from project roles
    project_role_user_emails: list[str] = []
    project_role_groups: list[str] = []
    if HOLDER_TYPE_PROJECT_ROLE in holder_map:
        project_role_user_emails, project_role_groups = (
            _get_user_emails_and_groups_from_project_roles(
                jira_client=jira_client,
                jira_project=jira_project,
                project_role_holders=holder_map[HOLDER_TYPE_PROJECT_ROLE],
            )
        )
    else:
        logger.info(
            "Jira project %s has no projectRole holders; project-role groups will be empty",
            jira_project,
        )

    # Get groups directly assigned in permission scheme (common in Data Center)
    # Format: {'type': 'group', 'parameter': 'group-name', 'expand': 'group'}
    direct_groups: list[str] = []
    if HOLDER_TYPE_GROUP in holder_map:
        for group_holder in holder_map[HOLDER_TYPE_GROUP]:
            group_name = _get_role_id(group_holder)
            if group_name:
                direct_groups.append(group_name)
            else:
                logger.error(
                    "Jira project %s group holder has no parameter/value; holder=%s",
                    jira_project,
                    group_holder,
                )
        if not direct_groups:
            logger.warning(
                "Jira project %s has %s direct group holders but resolved zero direct "
                "groups; group_holders=%s",
                jira_project,
                len(holder_map[HOLDER_TYPE_GROUP]),
                holder_map[HOLDER_TYPE_GROUP],
            )
    else:
        logger.info(
            "Jira project %s has no direct group holders; direct groups will be empty",
            jira_project,
        )

    external_user_emails = set(user_emails + project_role_user_emails)
    external_user_group_ids = set(project_role_groups + direct_groups)
    has_supported_static_holders = any(
        holder_type in holder_map for holder_type in SUPPORTED_STATIC_HOLDER_TYPES
    )

    if not external_user_group_ids:
        logger.warning(
            "Jira project %s resolved zero external groups; holder_counts=%s "
            "unsupported_holder_counts=%s direct_group_holder_count=%s "
            "direct_group_count=%s project_role_holder_count=%s "
            "project_role_group_count=%s explicit_user_email_count=%s "
            "project_role_user_email_count=%s",
            jira_project,
            holder_counts,
            unsupported_holder_counts,
            len(holder_map.get(HOLDER_TYPE_GROUP, [])),
            len(direct_groups),
            len(holder_map.get(HOLDER_TYPE_PROJECT_ROLE, [])),
            len(project_role_groups),
            len(user_emails),
            len(project_role_user_emails),
        )

    if not external_user_emails and not external_user_group_ids:
        if has_supported_static_holders:
            logger.error(
                "Jira project %s resolved to empty private ExternalAccess; "
                "holder_counts=%s unsupported_holder_counts=%s",
                jira_project,
                holder_counts,
                unsupported_holder_counts,
            )
        else:
            logger.warning(
                "Jira project %s resolved to empty private ExternalAccess from "
                "unsupported or dynamic-only %s holders; holder_counts=%s "
                "unsupported_holder_counts=%s",
                jira_project,
                BROWSE_PROJECTS_PERMISSION,
                holder_counts,
                unsupported_holder_counts,
            )

    return ExternalAccess(
        external_user_emails=external_user_emails,
        external_user_group_ids=external_user_group_ids,
        is_public=False,
    )


def get_project_permissions(
    jira_client: JIRA,
    jira_project: str,
    add_prefix: bool = False,
) -> ExternalAccess | None:
    """
    Get project permissions from Jira.

    add_prefix: When True, prefix group IDs with source type (for indexing path).
               When False (default), leave unprefixed (for permission sync path).
    """
    project_permissions: PermissionScheme = jira_client.project_permissionscheme(
        project=jira_project
    )

    if not hasattr(project_permissions, "permissions"):
        logger.error("Project %s has no permissions attribute", jira_project)
        return None

    if not isinstance(project_permissions.permissions, list):
        logger.error("Project %s permissions is not a list", jira_project)
        return None

    holder_map = _build_holder_map(permissions=project_permissions.permissions)
    logger.info(
        "Jira project %s %s holder summary; permission_count=%s holder_counts=%s "
        "unsupported_holder_counts=%s",
        jira_project,
        BROWSE_PROJECTS_PERMISSION,
        len(project_permissions.permissions),
        _get_holder_counts(holder_map),
        _get_unsupported_holder_counts(holder_map),
    )

    external_access = _build_external_access_from_holder_map(
        jira_client=jira_client, jira_project=jira_project, holder_map=holder_map
    )

    # Prefix group IDs with source type if requested (for indexing path)
    if add_prefix and external_access and external_access.external_user_group_ids:
        prefixed_groups = {
            build_ext_group_name_for_onyx(g, DocumentSource.JIRA)
            for g in external_access.external_user_group_ids
        }
        return ExternalAccess(
            external_user_emails=external_access.external_user_emails,
            external_user_group_ids=prefixed_groups,
            is_public=external_access.is_public,
        )

    return external_access
