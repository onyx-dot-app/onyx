from typing import Annotated, Self

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
)

_REPOSITORIES = "repositories"
_PROJECTS = "projects"


def _has_items(comma_separated: str | None) -> bool:
    return any(item.strip() for item in (comma_separated or "").split(","))


class BitbucketConnectorConfig(ConnectorConfig):
    # Document ids contain the workspace.
    workspace: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    repositories: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_PROJECTS,),
        ),
    ] = None
    projects: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_REPOSITORIES,),
        ),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        # Repositories take precedence over projects, and the form keeps the
        # value of each tab. A change between the repository and project modes
        # replaces one set of repositories with another.
        old_repo_mode = _has_items(old.repositories)
        new_repo_mode = _has_items(new.repositories)
        if old_repo_mode and new_repo_mode:
            return {_PROJECTS: ScopeDirection.NONE}
        if old_repo_mode != new_repo_mode and (
            _has_items(old.projects) or _has_items(new.projects)
        ):
            return {
                _REPOSITORIES: ScopeDirection.UNKNOWN,
                _PROJECTS: ScopeDirection.UNKNOWN,
            }
        return {}
