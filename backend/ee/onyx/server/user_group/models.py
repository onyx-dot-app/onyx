from uuid import UUID

from pydantic import BaseModel, Field

from onyx.auth.permissions import Permission
from onyx.db.models import UserGroup as UserGroupModel
from onyx.server.documents.models import (
    ConnectorCredentialPairDescriptor,
    ConnectorSnapshot,
    CredentialSnapshot,
)
from onyx.server.features.document_set.models import DocumentSet
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.server.manage.models import UserInfo, UserPreferences


class UserGroup(BaseModel):
    id: int
    name: str
    users: list[UserInfo]
    manager_ids: list[str]
    cc_pairs: list[ConnectorCredentialPairDescriptor]
    document_sets: list[DocumentSet]
    personas: list[PersonaSnapshot]
    is_up_to_date: bool
    is_up_for_deletion: bool
    is_default: bool
    # Members may start incognito chats when availability is groups-only.
    incognito_enabled: bool
    # Per-action affordance map ({"manage": true, ...}) the client reads to show/hide
    # controls. Empty default = every action denied (missing key is false), so it fails
    # closed. Only the list-groups endpoint fills it in; the mutation routes leave it empty.
    permissions: dict[str, bool] = Field(default_factory=dict)

    @classmethod
    def from_model(
        cls,
        user_group_model: UserGroupModel,
        *,
        mask_credential_prefix: bool,
        permissions: dict[str, bool] | None = None,
    ) -> "UserGroup":
        return cls(
            permissions=permissions or {},
            id=user_group_model.id,
            name=user_group_model.name,
            manager_ids=[
                str(relationship.user_id)
                for relationship in user_group_model.user_group_relationships
                if relationship.is_manager and relationship.user_id is not None
            ],
            users=[
                UserInfo(
                    id=str(user.id),
                    email=user.email,
                    is_active=user.is_active,
                    is_superuser=user.is_superuser,
                    is_verified=user.is_verified,
                    account_type=user.account_type,
                    preferences=UserPreferences(
                        default_model=user.default_model,
                        chosen_assistants=user.chosen_assistants,
                    ),
                )
                for user in user_group_model.users
            ],
            cc_pairs=[
                ConnectorCredentialPairDescriptor(
                    id=cc_pair_relationship.cc_pair.id,
                    name=cc_pair_relationship.cc_pair.name,
                    connector=ConnectorSnapshot.from_connector_db_model(
                        cc_pair_relationship.cc_pair.connector,
                        credential_ids=[cc_pair_relationship.cc_pair.credential_id],
                    ),
                    credential=CredentialSnapshot.from_credential_db_model(
                        cc_pair_relationship.cc_pair.credential,
                        mask_credential_prefix=mask_credential_prefix,
                    ),
                    access_type=cc_pair_relationship.cc_pair.access_type,
                )
                for cc_pair_relationship in user_group_model.cc_pair_relationships
                if cc_pair_relationship.is_current
            ],
            document_sets=[
                DocumentSet.from_model(
                    ds, mask_credential_prefix=mask_credential_prefix
                )
                for ds in user_group_model.document_sets
            ],
            personas=[
                PersonaSnapshot.from_model(persona)
                for persona in user_group_model.personas
                if not persona.deleted
            ],
            is_up_to_date=user_group_model.is_up_to_date,
            is_up_for_deletion=user_group_model.is_up_for_deletion,
            is_default=user_group_model.is_default,
            incognito_enabled=user_group_model.incognito_enabled,
        )


class MinimalUserGroupSnapshot(BaseModel):
    id: int
    name: str
    is_default: bool

    @classmethod
    def from_model(cls, user_group_model: UserGroupModel) -> "MinimalUserGroupSnapshot":
        return cls(
            id=user_group_model.id,
            name=user_group_model.name,
            is_default=user_group_model.is_default,
        )


class UserGroupCreate(BaseModel):
    name: str
    user_ids: list[UUID]
    cc_pair_ids: list[int]


class UserGroupUpdate(BaseModel):
    user_ids: list[UUID]
    # None leaves the connector links alone. Without it, changing a roster meant
    # reading every linked cc-pair back and resending it, so a link added in
    # between was reverted. add_users_to_user_group already preserves them.
    cc_pair_ids: list[int] | None = None


class UserGroupIncognitoUpdate(BaseModel):
    enabled: bool


class AddUsersToUserGroupRequest(BaseModel):
    user_ids: list[UUID]


class UserGroupRename(BaseModel):
    id: int
    name: str


class UpdateGroupAgentsRequest(BaseModel):
    added_agent_ids: list[int]
    removed_agent_ids: list[int]


class UpdateGroupDocumentSetsRequest(BaseModel):
    added_document_set_ids: list[int]
    removed_document_set_ids: list[int]


class SetGroupManagerRequest(BaseModel):
    user_id: UUID
    is_manager: bool


class BulkSetPermissionsRequest(BaseModel):
    permissions: list[Permission]
