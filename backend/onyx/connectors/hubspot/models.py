from pydantic import BaseModel, Field


class HubSpotObjectSpec(BaseModel):
    # HubSpot's id for the type, used in record URLs and HCRNs.
    type_id: str
    # Singular noun in document ids, as in hubspot_deal_<id>.
    document_noun: str
    # Search filters on this. Contacts name it differently.
    modified_date_property: str


class HubSpotUser(BaseModel):
    id: int
    email: str | None = None


# Api* models validate HubSpot's raw REST answers. The listed fields are
# required, so a body of the wrong shape fails the call instead of reading as
# an empty answer that would hide records.
class ApiPagingNext(BaseModel):
    after: str | None = None


class ApiPaging(BaseModel):
    next: ApiPagingNext | None = None


class ApiUsersResponse(BaseModel):
    results: list[HubSpotUser]
    paging: ApiPaging | None = None


class ApiActionPermittedUsers(BaseModel):
    permitted_users: list[int] = Field(default_factory=list, alias="permittedUsers")


class ApiPermittedUsersResponse(BaseModel):
    # HCRN to action to the users allowed that action.
    resources: dict[str, dict[str, ApiActionPermittedUsers]]
