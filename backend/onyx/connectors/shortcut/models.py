from pydantic import BaseModel, Field
from onyx.connectors.models import ConnectorCheckpoint


class ShortcutEpic(BaseModel):
    id: int
    name: str
    description: str | None = None
    state: str | None = None
    app_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ShortcutComment(BaseModel):
    id: int
    text: str
    author_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ShortcutTask(BaseModel):
    id: int
    description: str
    complete: bool = False


class ShortcutStory(BaseModel):
    id: int
    name: str
    description: str | None = None
    story_type: str = "feature"
    workflow_state_id: int | None = None
    epic_id: int | None = None
    project_id: int | None = None
    app_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    comments: list[ShortcutComment] = Field(default_factory=list)
    tasks: list[ShortcutTask] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    completed: bool = False


class ShortcutConnectorCheckpoint(ConnectorCheckpoint):
    last_synced_epoch: int = 0
    synced_story_ids: list[int] = Field(default_factory=list)
