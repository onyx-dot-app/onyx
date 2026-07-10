from pydantic import BaseModel
from pydantic import Field

from onyx.access.models import ExternalAccess
from onyx.connectors.models import ConnectorCheckpoint


class BoxAccessContext(BaseModel):
    """Read access accumulated along a Box folder chain (collaborations,
    shared links, and owners). Box collaborations are set on folders and
    cascade to all descendants, so this context is passed down the traversal."""

    user_emails: set[str] = Field(default_factory=set)
    group_ids: set[str] = Field(default_factory=set)
    is_public: bool = False

    def merged_with(self, other: "BoxAccessContext") -> "BoxAccessContext":
        return BoxAccessContext(
            user_emails=self.user_emails | other.user_emails,
            group_ids=self.group_ids | other.group_ids,
            is_public=self.is_public or other.is_public,
        )

    def to_external_access(self) -> ExternalAccess:
        return ExternalAccess(
            external_user_emails=self.user_emails,
            external_user_group_ids=self.group_ids,
            is_public=self.is_public,
        )


class BoxFolderFrontierEntry(BaseModel):
    folder_id: str
    display_name: str
    parent_folder_id: str | None = None
    path: str
    # While queued: access inherited from ancestor folders. Expanded with the
    # folder's own collaborations/shared link when the folder starts processing.
    # None outside permission-sync runs.
    access: BoxAccessContext | None = None


class BoxConnectorCheckpoint(ConnectorCheckpoint):
    # BFS frontier of folders left to process. None means the traversal has not
    # been seeded from the configured entry folders yet.
    todo: list[BoxFolderFrontierEntry] | None = None
    # Folder currently being paginated, with its opaque Box page marker.
    current: BoxFolderFrontierEntry | None = None
    current_marker: str | None = None
    # Folder IDs already processed, so overlapping/duplicate entry roots (e.g.
    # a folder and one of its ancestors both configured) don't double-index.
    seen_folder_ids: set[str] = Field(default_factory=set)
