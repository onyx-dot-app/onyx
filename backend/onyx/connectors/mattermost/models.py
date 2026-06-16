"""Typed shapes for the Mattermost REST API (v4) payloads the connector reads.

These mirror the subset of fields the connector uses; Mattermost returns more.
Timestamps (`create_at`, `update_at`, `edit_at`, `delete_at`) are Unix milliseconds.
"""
from typing_extensions import NotRequired
from typing_extensions import TypedDict


class Team(TypedDict):
    id: str
    name: str  # URL slug, used in permalinks
    display_name: str


class Channel(TypedDict):
    id: str
    team_id: str
    # "O" = public/open, "P" = private, "D" = direct message, "G" = group message
    type: str
    name: str
    display_name: str
    header: NotRequired[str]
    purpose: NotRequired[str]
    delete_at: NotRequired[int]  # > 0 means archived


class Post(TypedDict):
    id: str
    create_at: int
    update_at: int
    edit_at: NotRequired[int]
    delete_at: NotRequired[int]
    user_id: str
    channel_id: str
    root_id: str  # "" for a root post; otherwise the thread's root post id
    message: str
    type: str  # "" for normal user posts; "system_*" for system messages
    hashtags: NotRequired[str]


class PostList(TypedDict):
    order: list[str]  # post ids, newest-first within the page
    posts: dict[str, Post]
    next_post_id: NotRequired[str]
    prev_post_id: NotRequired[str]  # cursor for the next (older) page
    has_next: NotRequired[bool]
