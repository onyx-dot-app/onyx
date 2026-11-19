from collections.abc import Iterable

from onyx.configs.constants import DocumentSource

USER_EMAIL_ACL_PREFIX = "user_email:"
EXTERNAL_GROUP_ACL_PREFIX = "external_group:"


def prefix_user_email(user_email: str) -> str:
    """Prefixes a user email to eliminate collision with group names.
    This applies to both a Onyx user and an External user, this is to make the query time
    more efficient"""
    return f"{USER_EMAIL_ACL_PREFIX}{user_email}"


def prefix_user_group(user_group_name: str) -> str:
    """Prefixes a user group name to eliminate collision with user emails.
    This assumes that user ids are prefixed with a different prefix."""
    return f"group:{user_group_name}"


def prefix_external_group(ext_group_name: str) -> str:
    """Prefixes an external group name to eliminate collision with user emails / Onyx groups."""
    return f"{EXTERNAL_GROUP_ACL_PREFIX}{ext_group_name}"


def build_ext_group_name_for_onyx(ext_group_name: str, source: DocumentSource) -> str:
    """
    External groups may collide across sources, every source needs its own prefix.
    NOTE: the name is lowercased to handle case sensitivity for group names
    """
    return f"{source.value}_{ext_group_name}".lower()


# Sources whose connectors yield bare group ids on every path, so the indexing
# and hierarchy writers add the prefix. Group sync and doc sync add it for every
# source. A source joins when its connector stops prefixing; the set goes away
# once every source has joined.
SOURCES_YIELDING_BARE_GROUP_IDS: frozenset[DocumentSource] = frozenset(
    {
        DocumentSource.AZURE_DATALAKE,
        DocumentSource.BOX,
        DocumentSource.CANVAS,
        DocumentSource.CONFLUENCE,
        DocumentSource.EGNYTE,
        DocumentSource.GITHUB,
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.JIRA,
        DocumentSource.LINEAR,
        DocumentSource.ONEDRIVE,
        DocumentSource.SHAREPOINT,
        DocumentSource.TEAMS,
        DocumentSource.YOUTRACK,
        DocumentSource.ZOOM,
    }
)


def build_ext_group_names_for_storage(
    group_ids: Iterable[str], source: DocumentSource | None
) -> set[str]:
    """The stored form of the group ids a connector yielded for `source`."""
    if source is None or source not in SOURCES_YIELDING_BARE_GROUP_IDS:
        return set(group_ids)
    return {build_ext_group_name_for_onyx(group_id, source) for group_id in group_ids}


def build_domain_group_id(domain: str) -> str:
    """Group id for "everyone at <domain>" Drive shares. The Drive group sync
    populates it with the real Workspace roster for the domain, so membership is
    Google's own rather than inferred from a user's email string."""
    return f"domain:{domain.lower()}"
