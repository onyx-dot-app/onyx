from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

_ItemT = TypeVar("_ItemT")


class HubSpotObjectSpec(BaseModel):
    # HubSpot's id for the type, used in record URLs and HCRNs.
    type_id: str
    # Singular noun in document ids, as in hubspot_deal_<id>.
    document_noun: str
    # Search filters on this. Contacts name it differently.
    modified_date_property: str
    # The private-app scope that reads the type. HubSpot names the ticket scope
    # plain `tickets`, outside the crm.objects.* pattern.
    read_scope: str


class HubSpotPage(BaseModel, Generic[_ItemT]):
    items: list[_ItemT]
    next_after: str | None = None


class HubSpotAssociationIds(BaseModel):
    ids: list[str]
    # True when HubSpot paged the inline list, so it is incomplete.
    has_more: bool


class HubSpotRecord(BaseModel):
    id: str
    properties: dict[str, str | None] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # Inline association ids by object type. None when none were requested or
    # HubSpot sent none.
    associations: dict[str, HubSpotAssociationIds] | None = None


class HubSpotUser(BaseModel):
    id: int
    email: str | None = None


class HubSpotDocumentParts(BaseModel):
    """The per-type half of a document. The rest is shared by every type."""

    title: str
    text: str
    metadata: dict[str, str]


# Api* models validate HubSpot's raw answers: the SDK's to_dict() shapes and
# the REST bodies of the APIs the SDK has no client for. The listed fields are
# required, so a body of the wrong shape fails the call instead of reading as
# an empty answer that would hide records.
class ApiPagingNext(BaseModel):
    after: str | None = None


class ApiPaging(BaseModel):
    next: ApiPagingNext | None = None


class ApiAssociatedId(BaseModel):
    id: str


class ApiAssociationCollection(BaseModel):
    results: list[ApiAssociatedId]
    paging: ApiPaging | None = None


class ApiRecord(BaseModel):
    id: str
    properties: dict[str, str | None] | None = None
    created_at: datetime
    updated_at: datetime
    associations: dict[str, ApiAssociationCollection] | None = None


class ApiRecordPage(BaseModel):
    results: list[ApiRecord]
    paging: ApiPaging | None = None


class ApiAssociation(BaseModel):
    to_object_id: int


class ApiAssociationPage(BaseModel):
    results: list[ApiAssociation]
    paging: ApiPaging | None = None


class ApiPortalInfo(BaseModel):
    portal_id: int = Field(alias="portalId")


class ApiUsersResponse(BaseModel):
    results: list[HubSpotUser]
    paging: ApiPaging | None = None


class ApiActionPermittedUsers(BaseModel):
    permitted_users: list[int] = Field(default_factory=list, alias="permittedUsers")


class ApiPermittedUsersResponse(BaseModel):
    # HCRN to action to the users allowed that action.
    resources: dict[str, dict[str, ApiActionPermittedUsers]]
