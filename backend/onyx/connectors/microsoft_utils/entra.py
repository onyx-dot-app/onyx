"""Typed Entra directory operations shared by Microsoft connectors."""

from collections.abc import Callable, Generator
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from onyx.connectors.microsoft_utils.graph_gateway import build_graph_user_url

ENTRA_PAGE_SIZE = 999
MAX_ENTRA_COLLECTION_PAGES = 100_000
ENTRA_USER_SELECT = "id,userPrincipalName,mail,displayName,userType,accountEnabled"
ENTRA_GROUP_ID_SELECT = "id"
ENTRA_NAMED_GROUP_SELECT = "id,displayName"
ENTRA_GROUP_SELECT = "id,displayName,visibility"
ENTRA_GROUP_MEMBER_SELECT = "id,userPrincipalName,mail"
ENABLED_USERS_FILTER = "accountEnabled eq true"

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


class EntraGroup(EntraModel):
    id: str
    display_name: str | None = Field(default=None, alias="displayName")
    visibility: str | None = None


class EntraDirectoryObject(EntraModel):
    id: str
    odata_type: EntraDirectoryObjectType | str | None = Field(
        default=None, alias="@odata.type"
    )
    mail: str | None = None
    user_principal_name: str | None = Field(default=None, alias="userPrincipalName")


EntraItem = TypeVar("EntraItem", bound=EntraModel)


class EntraPage(BaseModel, Generic[EntraItem]):
    items: list[EntraItem]
    next_link: str | None = None


def fetch_entra_page(
    get_json: GraphJsonGetter,
    *,
    url: str,
    item_model: type[EntraItem],
    select_fields: str,
    next_link: str | None = None,
    page_size: int = ENTRA_PAGE_SIZE,
    filter_expression: str | None = None,
) -> EntraPage[EntraItem]:
    params = None
    if next_link is None:
        params = {"$select": select_fields, "$top": str(page_size)}
        if filter_expression:
            params["$filter"] = filter_expression
    data = get_json(next_link or url, params)
    return EntraPage(
        items=[item_model.model_validate(item) for item in data.get("value", [])],
        next_link=data.get("@odata.nextLink"),
    )


def fetch_entra_user(
    get_json: GraphJsonGetter,
    graph_api_base: str,
    identifier: str,
) -> EntraUser:
    data = get_json(
        build_graph_user_url(graph_api_base, identifier),
        {"$select": ENTRA_USER_SELECT},
    )
    return EntraUser.model_validate(data)


def iter_entra_items(
    fetch_page: Callable[[str | None], EntraPage[EntraItem]],
    collection_name: str,
) -> Generator[EntraItem, None, None]:
    next_link: str | None = None
    for _ in range(MAX_ENTRA_COLLECTION_PAGES):
        request_url = next_link
        page = fetch_page(next_link)
        yield from page.items
        next_link = page.next_link
        if next_link is None:
            return
        if next_link == request_url:
            raise RuntimeError(f"{collection_name} returned a repeated cursor.")
    raise RuntimeError(f"{collection_name} exceeds the page limit.")
