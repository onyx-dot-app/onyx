from pydantic import BaseModel


class JiraIssueIdPage(BaseModel):
    """One page of a Cloud enhanced JQL search. ``next_page_token`` is None on
    the last page."""

    issue_ids: list[str]
    next_page_token: str | None


class JiraGroupPage(BaseModel):
    """The group names ``groups/picker`` returns. ``total`` is the number of
    groups that match, which can be larger than the names returned."""

    group_names: list[str]
    total: int | None
