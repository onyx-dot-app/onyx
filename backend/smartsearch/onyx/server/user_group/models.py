from uuid import UUID

from pydantic import BaseModel, Field

from onyx.db.models import UserGroup as UserGroupDbModel
from onyx.server.documents.models import (
    ConnectorCredentialPairDescriptor,
    ConnectorSnapshot,
    CredentialSnapshot,
)
from onyx.server.features.document_set.models import DocumentSet
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.server.manage.models import UserInfo, UserPreferences


class UserGroup(BaseModel):
    id: int = Field(
        description="Уникальный идентификатор группы",
    )
    name: str = Field(
        description="Название группы пользователей",
    )
    users: list[UserInfo] = Field(
        description="Список пользователей в группе,"
    )
    curator_ids: list[UUID] = Field(
        description="Идентификаторы кураторов группы",
    )
    cc_pairs: list[ConnectorCredentialPairDescriptor] = Field(
        description="Связанные коннектор-креденшиал пары"
    )
    document_sets: list[DocumentSet] = Field(
        description="Наборы документов доступные группе",
    )
    personas: list[PersonaSnapshot] = Field(
        description="Ассистенты, доступные группе",
    )
    is_up_to_date: bool = Field(
        description="Флаг актуальности синхронизации с Vespa"
    )
    is_up_for_deletion: bool = Field(
        description="Флаг помеченности на удаление"
    )

    @classmethod
    def from_model(cls, user_group_model: UserGroupDbModel) -> "UserGroup":
        return cls(
            id=user_group_model.id,
            name=user_group_model.name,
            users=[
                UserInfo(
                    id=str(user.id),
                    email=user.email,
                    is_active=user.is_active,
                    is_superuser=user.is_superuser,
                    is_verified=user.is_verified,
                    role=user.role,
                    preferences=UserPreferences(
                        default_model=user.default_model,
                        chosen_assistants=user.chosen_assistants,
                    ),
                )
                for user in user_group_model.users
            ],
            curator_ids=[
                user.user_id
                for user in user_group_model.user_group_relationships
                if user.is_curator and user.user_id is not None
            ],
            cc_pairs=[
                ConnectorCredentialPairDescriptor(
                    id=cc_pair_relationship.cc_pair.id,
                    name=cc_pair_relationship.cc_pair.name,
                    connector=ConnectorSnapshot.from_connector_db_model(
                        cc_pair_relationship.cc_pair.connector
                    ),
                    credential=CredentialSnapshot.from_credential_db_model(
                        cc_pair_relationship.cc_pair.credential
                    ),
                    access_type=cc_pair_relationship.cc_pair.access_type,
                )
                for cc_pair_relationship in user_group_model.cc_pair_relationships
                if cc_pair_relationship.is_current
            ],
            document_sets=[
                DocumentSet.from_model(ds) for ds in user_group_model.document_sets
            ],
            personas=[
                PersonaSnapshot.from_model(persona)
                for persona in user_group_model.personas
                if not persona.deleted
            ],
            is_up_to_date=user_group_model.is_up_to_date,
            is_up_for_deletion=user_group_model.is_up_for_deletion,
        )


class UserGroupCreate(BaseModel):
    name: str = Field(
        description="Название создаваемой группы пользователей",
    )
    user_ids: list[UUID] = Field(
        description="Список идентификаторов пользователей для добавления в группу",
    )
    cc_pair_ids: list[int] = Field(
        description="Список идентификаторов коннектор-креденшиал пар для связи с группой",
    )


class UserGroupUpdate(BaseModel):
    user_ids: list[UUID] = Field(
        description="Список идентификаторов пользователей группы",
    )
    cc_pair_ids: list[int] = Field(
        description="Список идентификаторов коннектор-креденшиал пар",
    )


class SetCuratorRequest(BaseModel):
    user_id: UUID = Field(
        description="Идентификатор пользователя для изменения прав куратора",
    )
    is_curator: bool = Field(
        description="Флаг назначения/снятия прав куратора",
    )
