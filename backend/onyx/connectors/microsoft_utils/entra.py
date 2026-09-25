"""Typed Entra directory operations shared by Microsoft connectors."""

from collections.abc import Callable, Generator
from enum import Enum
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from onyx.connectors.microsoft_utils.graph_gateway import build_graph_user_url

ENTRA_PAGE_SIZE = 999
MAX_ENTRA_COLLECTION_PAGES = 100_000
ENTRA_USER_SELECT = "id,userPrincipalName,mail,displayName,userType,accountEnabled"
ENTRA_GROUP_ID_SELECT = "id"
ENTRA_NAMED_GROUP_SELECT = "id,displayName"
ENTRA_GROUP_SELECT = "id,displayName,visibility"
ENTRA_GROUP_MEMBER_SELECT = "id,displayName,userPrincipalName,mail"
ENABLED_USERS_FILTER = "accountEnabled eq true"
GROUP_MEMBERS_RELATIONSHIP = "members"
TRANSITIVE_GROUP_MEMBERS_RELATIONSHIP = "transitiveMembers"

GraphJsonGetter = Callable[
    [str, dict[str, str] | None],
    dict[str, Any],
]


class EntraModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class EntraDirectoryObjectType(str, Enum):
    USER = "#microsoft.graph.user"
    GROUP = "#microsoft.graph.group"


class EntraUser(EntraModel):
    id: str
    user_principal_name: str | None = Field(default=None, alias="userPrincipalName")
    mail: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    user_type: str | None = Field(default=None, alias="userType")
    account_enabled: bool | None = Field(default=None, alias="accountEnabled")


class EntraUserPage(BaseModel):
    users: list[EntraUser]
    next_link: str | None = None


class EntraGroup(EntraModel):
    id: str
    display_name: str | None = Field(default=None, alias="displayName")
    visibility: str | None = None


class EntraGroupPage(BaseModel):
    groups: list[EntraGroup]
    next_link: str | None = None


class EntraDirectoryObject(EntraModel):
    id: str
    odata_type: EntraDirectoryObjectType | str | None = Field(
        default=None, alias="@odata.type"
    )
    display_name: str | None = Field(default=None, alias="displayName")
    mail: str | None = None
    user_principal_name: str | None = Field(default=None, alias="userPrincipalName")


class EntraDirectoryObjectPage(BaseModel):
    members: list[EntraDirectoryObject]
    next_link: str | None = None


EntraGroupPageFetcher = Callable[[str | None], EntraGroupPage]
EntraMemberPageFetcher = Callable[[str | None], EntraDirectoryObjectPage]


def iter_entra_groups(
    fetch_page: EntraGroupPageFetcher,
) -> Generator[EntraGroup, None, None]:
    next_link: str | None = None
    for _ in range(MAX_ENTRA_COLLECTION_PAGES):
        request_url = next_link
        page = fetch_page(next_link)
        yield from page.groups
        next_link = page.next_link
        if next_link is None:
            return
        if next_link == request_url:
            raise RuntimeError("Entra group listing returned a repeated cursor.")
    raise RuntimeError("Entra group listing exceeds the page limit.")


def iter_entra_group_members(
    group_id: str,
    fetch_page: EntraMemberPageFetcher,
) -> Generator[EntraDirectoryObject, None, None]:
    next_link: str | None = None
    for _ in range(MAX_ENTRA_COLLECTION_PAGES):
        request_url = next_link
        page = fetch_page(next_link)
        yield from page.members
        next_link = page.next_link
        if next_link is None:
            return
        if next_link == request_url:
            raise RuntimeError(
                f"Entra group `{group_id}` returned a repeated member cursor."
            )
    raise RuntimeError(f"Entra group `{group_id}` exceeds the member page limit.")


class EntraClient:
    """Source-neutral users, groups, and group membership Graph operations."""

    def __init__(self, get_json: GraphJsonGetter, graph_api_base: str) -> None:
        self._get_json = get_json
        self._graph_api_base = graph_api_base.rstrip("/")

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._get_json(url, params)

    def _users_page(
        self,
        *,
        next_link: str | None,
        page_size: int,
        enabled_only: bool,
    ) -> EntraUserPage:
        params: dict[str, str] | None = None
        url = next_link
        if url is None:
            url = f"{self._graph_api_base}/users"
            params = {
                "$select": ENTRA_USER_SELECT,
                "$top": str(page_size),
            }
            if enabled_only:
                params["$filter"] = ENABLED_USERS_FILTER
        data = self._get(url, params)
        return EntraUserPage(
            users=[EntraUser.model_validate(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
        )

    def list_users_page(
        self,
        *,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraUserPage:
        return self._users_page(
            next_link=next_link,
            page_size=page_size,
            enabled_only=False,
        )

    def list_enabled_users_page(
        self,
        *,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraUserPage:
        return self._users_page(
            next_link=next_link,
            page_size=page_size,
            enabled_only=True,
        )

    def get_user(self, identifier: str) -> EntraUser:
        data = self._get(
            build_graph_user_url(self._graph_api_base, identifier),
            {"$select": ENTRA_USER_SELECT},
        )
        return EntraUser.model_validate(data)

    def _groups_page(
        self,
        *,
        next_link: str | None,
        page_size: int,
        select_fields: str,
    ) -> EntraGroupPage:
        params: dict[str, str] | None = None
        url = next_link
        if url is None:
            url = f"{self._graph_api_base}/groups"
            params = {
                "$select": select_fields,
                "$top": str(page_size),
            }
        data = self._get(url, params)
        return EntraGroupPage(
            groups=[EntraGroup.model_validate(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
        )

    def list_group_ids_page(
        self,
        *,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraGroupPage:
        return self._groups_page(
            next_link=next_link,
            page_size=page_size,
            select_fields=ENTRA_GROUP_ID_SELECT,
        )

    def list_named_groups_page(
        self,
        *,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraGroupPage:
        return self._groups_page(
            next_link=next_link,
            page_size=page_size,
            select_fields=ENTRA_NAMED_GROUP_SELECT,
        )

    def list_groups_page(
        self,
        *,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraGroupPage:
        return self._groups_page(
            next_link=next_link,
            page_size=page_size,
            select_fields=ENTRA_GROUP_SELECT,
        )

    def _group_members_page(
        self,
        *,
        group_id: str,
        next_link: str | None,
        transitive: bool,
        page_size: int,
    ) -> EntraDirectoryObjectPage:
        params: dict[str, str] | None = None
        url = next_link
        if url is None:
            relationship = (
                TRANSITIVE_GROUP_MEMBERS_RELATIONSHIP
                if transitive
                else GROUP_MEMBERS_RELATIONSHIP
            )
            url = f"{self._graph_api_base}/groups/{quote(group_id)}/{relationship}"
            params = {
                "$select": ENTRA_GROUP_MEMBER_SELECT,
                "$top": str(page_size),
            }
        data = self._get(url, params)
        return EntraDirectoryObjectPage(
            members=[
                EntraDirectoryObject.model_validate(raw)
                for raw in data.get("value", [])
            ],
            next_link=data.get("@odata.nextLink"),
        )

    def list_group_members_page(
        self,
        *,
        group_id: str,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraDirectoryObjectPage:
        return self._group_members_page(
            group_id=group_id,
            next_link=next_link,
            transitive=False,
            page_size=page_size,
        )

    def list_transitive_group_members_page(
        self,
        *,
        group_id: str,
        next_link: str | None = None,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> EntraDirectoryObjectPage:
        return self._group_members_page(
            group_id=group_id,
            next_link=next_link,
            transitive=True,
            page_size=page_size,
        )

    def iter_groups(
        self,
        *,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> Generator[EntraGroup, None, None]:
        yield from iter_entra_groups(
            lambda next_link: self.list_named_groups_page(
                next_link=next_link,
                page_size=page_size,
            )
        )

    def iter_group_members(
        self,
        group_id: str,
        *,
        page_size: int = ENTRA_PAGE_SIZE,
    ) -> Generator[EntraDirectoryObject, None, None]:
        yield from iter_entra_group_members(
            group_id,
            lambda next_link: self.list_group_members_page(
                group_id=group_id,
                next_link=next_link,
                page_size=page_size,
            ),
        )
