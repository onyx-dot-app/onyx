from pydantic import BaseModel, Field

from onyx.connectors.models import ConnectorCheckpoint


class ServiceDeskInfo(BaseModel):
    id: str
    project_id: str | None = None
    project_name: str | None = None
    project_key: str | None = None
    portal_url: str | None = None


class ServiceDeskQueueInfo(BaseModel):
    id: str
    name: str
    jql: str | None = None
    issue_count: int | None = None
    service_desk_id: str | None = None


class SlaMetric(BaseModel):
    name: str
    breached: bool | None = None
    paused: bool | None = None
    within_calendar_hours: bool | None = None
    goal_duration: str | None = None
    elapsed_time: str | None = None
    remaining_time: str | None = None
    is_ongoing: bool = False

    @property
    def ongoing(self) -> bool:
        return self.is_ongoing

    @property
    def elapsed_friendly(self) -> str | None:
        return self.elapsed_time

    @property
    def goal_friendly(self) -> str | None:
        return self.goal_duration

    @property
    def remaining_friendly(self) -> str | None:
        return self.remaining_time

    @property
    def status(self) -> str:
        if self.breached is True:
            return "BREACHED (IN_PROGRESS)" if self.is_ongoing else "BREACHED"
        if self.paused:
            return "PAUSED"
        if self.is_ongoing:
            return "IN_PROGRESS"
        if self.breached is False:
            return "MET"
        return "COMPLETED"


class JsmComment(BaseModel):
    id: str
    author_name: str | None = None
    author_email: str | None = None
    body: str
    public: bool = True
    created: str | None = None


class JsmAttachment(BaseModel):
    id: str
    filename: str
    mime_type: str | None = None
    size: int | None = None
    content_url: str | None = None
    created: str | None = None
    author_name: str | None = None
    extracted_text: str | None = None

    @property
    def author(self) -> str | None:
        return self.author_name


class JsmChangelogEntry(BaseModel):
    id: str | None = None
    author_name: str | None = None
    created: str | None = None
    field: str
    from_string: str | None = None
    to_string: str | None = None


class JiraServiceManagementCheckpoint(ConnectorCheckpoint):
    service_desk_ids: list[str] | None = None
    current_service_desk_idx: int = 0
    queue_ids_for_current_desk: list[str] | None = None
    current_queue_idx: int = 0
    start_at: int = 0
    start_offset: int = 0
    next_page_token: str | None = None
    pending_issue_ids: list[str] = Field(default_factory=list)
    ids_done: bool = False
    seen_issue_keys: list[str] = Field(default_factory=list)
    seen_hierarchy_node_ids: list[str] = Field(default_factory=list)
