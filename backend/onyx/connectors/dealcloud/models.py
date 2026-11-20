from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from onyx.connectors.models import ConnectorCheckpoint

# Field types that hold file bytes or internal ids, which have no text to index.
FIELD_TYPE_BINARY: int = 13
FIELD_TYPE_ENTRY_LIST_ID: int = 14
FIELD_TYPE_IMAGE: int = 16
FIELD_TYPE_DATA_SOURCE: int = 17

SYSTEM_FIELD_CREATED: int = 1
SYSTEM_FIELD_CREATED_BY: int = 2
SYSTEM_FIELD_MODIFIED: int = 3
SYSTEM_FIELD_NAME: int = 9

# The entry list type of the Attachment object, whose entries are file bytes.
ENTRY_LIST_TYPE_ATTACHMENT: int = 7


class DealCloudEntryType(BaseModel):
    """An object of the site, such as Company or Deal. Each site defines its own."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    api_name: str = Field(alias="apiName")
    plural_name: str = Field(alias="pluralName")
    entry_list_type: int = Field(alias="entryListType")


class DealCloudField(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # The key of this field's value in a row.
    api_name: str = Field(alias="apiName")
    name: str
    field_type: int = Field(alias="fieldType")
    system_field_type: int = Field(default=0, alias="systemFieldType")


class DealCloudRow(BaseModel):
    entry_id: int
    # Field values by api name. A reference, choice or user value is an object
    # with a `name`, and a multi-value field holds a list of them.
    values: dict[str, JsonValue]
    # True for an entry whose data alone passes the size cap. It has no values.
    is_too_large: bool = False


class DealCloudObjectWalk(BaseModel):
    """What a run reads once for the object it walks, kept across its
    load_from_checkpoint calls."""

    entry_type_id: int
    fields: list[DealCloudField]
    # Ascending ids of the entries to index.
    entry_ids: list[int]
    # True when the ids are every entry, not only the changed ones.
    is_full: bool


class DealCloudCheckpoint(ConnectorCheckpoint):
    # Ids of objects still to index, listed on a run's first call. The first
    # one is the object being walked.
    entry_type_ids: list[int] | None = None
    # The last entry read of the object being walked. Entries are walked in
    # ascending id order.
    last_entry_id: int | None = None


class DealCloudUser(BaseModel):
    id: int
    email: str | None = None


class DealCloudUserGroupRef(BaseModel):
    id: int


class DealCloudReadCapability(BaseModel):
    all_entry_lists_allowed: bool = Field(default=False, alias="allEntryListsAllowed")


class DealCloudEntryLevelCapabilities(BaseModel):
    read: DealCloudReadCapability = Field(default_factory=DealCloudReadCapability)


class DealCloudUserGroup(BaseModel):
    id: int
    # DealCloud's Read Data capability, "All" for every entry of the allowed objects.
    read_data: str | None = Field(default=None, alias="readData")
    entry_level_capabilities: DealCloudEntryLevelCapabilities = Field(
        default_factory=DealCloudEntryLevelCapabilities,
        alias="entryLevelCapabilities",
    )
    users: list[int] = Field(default_factory=list)

    # DealCloud sends the members as `users` or as `memberIds`, and each one
    # as an id or as an object with an id.
    @model_validator(mode="before")
    @classmethod
    def _member_ids(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        members: object = data.get("users") or data.get("memberIds") or []
        if not isinstance(members, list):
            return data
        return {
            **data,
            "users": [
                member.get("id") if isinstance(member, dict) else member
                for member in members
            ],
        }
