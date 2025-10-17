import datetime
import json
from typing import Any
from typing import Literal
from typing import NotRequired
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy.orm import validates
from typing_extensions import TypedDict  # noreorder
from uuid import UUID
from pydantic import ValidationError

from sqlalchemy.dialects.postgresql import UUID as PGUUID

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseOAuthAccountTableUUID
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import TIMESTAMPAware
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import desc
from sqlalchemy import Enum
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import func
from sqlalchemy import Index
from sqlalchemy import Integer

from sqlalchemy import Sequence
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy.types import LargeBinary
from sqlalchemy.types import TypeDecorator
from sqlalchemy import PrimaryKeyConstraint
from sqlalchemy import ForeignKeyConstraint

from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImageFullResult,
)
from onyx.auth.schemas import UserRole
from onyx.configs.chat_configs import NUM_POSTPROCESSED_RESULTS
from onyx.configs.constants import (
    DEFAULT_BOOST,
    FederatedConnectorSource,
    MilestoneRecordType,
)
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import MessageType
from onyx.db.enums import (
    AccessType,
    EmbeddingPrecision,
    IndexingMode,
    SyncType,
    SyncStatus,
    MCPAuthenticationType,
    UserFileStatus,
    MCPAuthenticationPerformer,
    MCPTransport,
)
from onyx.configs.constants import NotificationType
from onyx.configs.constants import SearchFeedbackType
from onyx.configs.constants import TokenRateLimitScope
from onyx.connectors.models import InputType
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PermissionSyncStatus
from onyx.db.enums import TaskStatus
from onyx.db.pydantic_type import PydanticListType, PydanticType
from onyx.kg.models import KGEntityTypeAttributes
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.context.search.enums import RecencyBiasSetting
from onyx.kg.models import KGStage
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes
from onyx.utils.headers import HeaderItemDict
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import RerankerProvider
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose

logger = setup_logger()

PROMPT_LENGTH = 5_000_000


class Base(DeclarativeBase):
    __abstract__ = True


class EncryptedString(TypeDecorator):
    impl = LargeBinary
    # This type's behavior is fully deterministic and doesn't depend on any external factors.
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> bytes | None:
        if value is not None:
            return encrypt_string_to_bytes(value)
        return value

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> str | None:
        if value is not None:
            return decrypt_bytes_to_string(value)
        return value


class EncryptedJson(TypeDecorator):
    impl = LargeBinary
    # This type's behavior is fully deterministic and doesn't depend on any external factors.
    cache_ok = True

    def process_bind_param(self, value: dict | None, dialect: Dialect) -> bytes | None:
        if value is not None:
            json_str = json.dumps(value)
            return encrypt_string_to_bytes(json_str)
        return value

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> dict | None:
        if value is not None:
            json_str = decrypt_bytes_to_string(value)
            return json.loads(json_str)
        return value


class NullFilteredString(TypeDecorator):
    impl = String
    # This type's behavior is fully deterministic and doesn't depend on any external factors.
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is not None and "\x00" in value:
            logger.warning(f"NUL characters found in value: {value}")
            return value.replace("\x00", "")
        return value

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


"""
Auth/Authz (users, permissions, access) Tables
"""


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    # even an almost empty token from keycloak will not fit the default 1024 bytes
    access_token: Mapped[str] = mapped_column(Text, nullable=False)  # type: ignore
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)  # type: ignore


class User(SQLAlchemyBaseUserTableUUID, Base):
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined", cascade="all, delete-orphan"
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, default=UserRole.BASIC)
    )

    """
    Preferences probably should be in a separate table at some point, but for now
    putting here for simpicity
    """

    temperature_override_enabled: Mapped[bool | None] = mapped_column(
        Boolean, default=None
    )
    auto_scroll: Mapped[bool | None] = mapped_column(Boolean, default=None)
    shortcut_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # personalization fields are exposed via the chat user settings "Personalization" tab
    personal_name: Mapped[str | None] = mapped_column(String, nullable=True)
    personal_role: Mapped[str | None] = mapped_column(String, nullable=True)
    use_memories: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    chosen_assistants: Mapped[list[int] | None] = mapped_column(
        postgresql.JSONB(), nullable=True, default=None
    )
    visible_assistants: Mapped[list[int]] = mapped_column(
        postgresql.JSONB(), nullable=False, default=[]
    )
    hidden_assistants: Mapped[list[int]] = mapped_column(
        postgresql.JSONB(), nullable=False, default=[]
    )

    pinned_assistants: Mapped[list[int] | None] = mapped_column(
        postgresql.JSONB(), nullable=True, default=None
    )

    oidc_expiry: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMPAware(timezone=True), nullable=True
    )

    default_model: Mapped[str] = mapped_column(Text, nullable=True)
    # organized in typical structured fashion
    # formatted as `displayName__provider__modelName`

    # relationships
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential", back_populates="user", lazy="joined"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="user"
    )

    input_prompts: Mapped[list["InputPrompt"]] = relationship(
        "InputPrompt", back_populates="user"
    )
    # Personas owned by this user
    personas: Mapped[list["Persona"]] = relationship("Persona", back_populates="user")
    # Custom tools created by this user
    custom_tools: Mapped[list["Tool"]] = relationship("Tool", back_populates="user")
    # Notifications for the UI
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="user"
    )
    cc_pairs: Mapped[list["ConnectorCredentialPair"]] = relationship(
        "ConnectorCredentialPair",
        back_populates="creator",
        primaryjoin="User.id == foreign(ConnectorCredentialPair.creator_id)",
    )
    projects: Mapped[list["UserProject"]] = relationship(
        "UserProject", back_populates="user"
    )
    files: Mapped[list["UserFile"]] = relationship("UserFile", back_populates="user")
    # MCP servers accessible to this user
    accessible_mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer", secondary="mcp_server__user", back_populates="users"
    )
    memories: Mapped[list["Memory"]] = relationship(
        "Memory",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @validates("email")
    def validate_email(self, key: str, value: str) -> str:
        return value.lower() if value else value

    @property
    def password_configured(self) -> bool:
        """
        Returns True if the user has at least one OAuth (or OIDC) account.
        """
        return not bool(self.oauth_accounts)


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    pass


class Memory(Base):
    __tablename__ = "memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    memory_text: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="memories")


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_api_key: Mapped[str] = mapped_column(String, unique=True)
    api_key_display: Mapped[str] = mapped_column(String, unique=True)
    # the ID of the "user" who represents the access credentials for the API key
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    # the ID of the user who owns the key
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Add this relationship to access the User object via user_id
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(primary_key=True)
    notif_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False)
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_shown: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    first_shown: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="notifications")
    additional_data: Mapped[dict | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )


"""
Association Tables
NOTE: must be at the top since they are referenced by other tables
"""


class Persona__DocumentSet(Base):
    __tablename__ = "persona__document_set"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id"), primary_key=True
    )


class Persona__User(Base):
    __tablename__ = "persona__user"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, nullable=True
    )


class DocumentSet__User(Base):
    __tablename__ = "document_set__user"

    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id"), primary_key=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, nullable=True
    )


class DocumentSet__ConnectorCredentialPair(Base):
    __tablename__ = "document_set__connector_credential_pair"

    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id"), primary_key=True
    )
    connector_credential_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"), primary_key=True
    )
    # if `True`, then is part of the current state of the document set
    # if `False`, then is a part of the prior state of the document set
    # rows with `is_current=False` should be deleted when the document
    # set is updated and should not exist for a given document set if
    # `DocumentSet.is_up_to_date == True`
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        primary_key=True,
    )

    document_set: Mapped["DocumentSet"] = relationship("DocumentSet")


class ChatMessage__SearchDoc(Base):
    __tablename__ = "chat_message__search_doc"

    chat_message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_message.id"), primary_key=True
    )
    search_doc_id: Mapped[int] = mapped_column(
        ForeignKey("search_doc.id"), primary_key=True
    )


class AgentSubQuery__SearchDoc(Base):
    __tablename__ = "agent__sub_query__search_doc"

    sub_query_id: Mapped[int] = mapped_column(
        ForeignKey("agent__sub_query.id", ondelete="CASCADE"), primary_key=True
    )
    search_doc_id: Mapped[int] = mapped_column(
        ForeignKey("search_doc.id"), primary_key=True
    )


class Document__Tag(Base):
    __tablename__ = "document__tag"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id"), primary_key=True, index=True
    )


class Persona__Tool(Base):
    """An entry in this table represents a tool that is **available** to a persona.
    It does NOT necessarily mean that the tool is actually usable to the persona.

    For example, a persona may have the image generation tool attached to it, even though
    the image generation tool is not set up / enabled. In this case, the tool should not
    show up in the UI for the persona + it should not be usable by the persona in chat.
    """

    __tablename__ = "persona__tool"

    persona_id: Mapped[int] = mapped_column(
        ForeignKey("persona.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tool.id", ondelete="CASCADE"), primary_key=True
    )


class StandardAnswer__StandardAnswerCategory(Base):
    __tablename__ = "standard_answer__standard_answer_category"

    standard_answer_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer.id"), primary_key=True
    )
    standard_answer_category_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer_category.id"), primary_key=True
    )


class SlackChannelConfig__StandardAnswerCategory(Base):
    __tablename__ = "slack_channel_config__standard_answer_category"

    slack_channel_config_id: Mapped[int] = mapped_column(
        ForeignKey("slack_channel_config.id"), primary_key=True
    )
    standard_answer_category_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer_category.id"), primary_key=True
    )


class ChatMessage__StandardAnswer(Base):
    __tablename__ = "chat_message__standard_answer"

    chat_message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_message.id", ondelete="CASCADE"), primary_key=True
    )
    standard_answer_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer.id"), primary_key=True
    )


"""
Documents/Indexing Tables
"""


class ConnectorCredentialPair(Base):
    """Connectors and Credentials can have a many-to-many relationship
    I.e. A Confluence Connector may have multiple admin users who can run it with their own credentials
    I.e. An admin user may use the same credential to index multiple Confluence Spaces
    """

    __tablename__ = "connector_credential_pair"
    is_user_file: Mapped[bool] = mapped_column(Boolean, default=False)
    # NOTE: this `id` column has to use `Sequence` instead of `autoincrement=True`
    # due to some SQLAlchemy quirks + this not being a primary key column
    id: Mapped[int] = mapped_column(
        Integer,
        Sequence("connector_credential_pair_id_seq"),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ConnectorCredentialPairStatus] = mapped_column(
        Enum(ConnectorCredentialPairStatus, native_enum=False), nullable=False
    )
    # this is separate from the `status` above, since a connector can be `INITIAL_INDEXING`, `ACTIVE`,
    # or `PAUSED` and still be in a repeated error state.
    in_repeated_error_state: Mapped[bool] = mapped_column(Boolean, default=False)
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("connector.id"), primary_key=True
    )

    deletion_failure_message: Mapped[str | None] = mapped_column(String, nullable=True)

    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credential.id"), primary_key=True
    )
    # controls whether the documents indexed by this CC pair are visible to all
    # or if they are only visible to those with that are given explicit access
    # (e.g. via owning the credential or being a part of a group that is given access)
    access_type: Mapped[AccessType] = mapped_column(
        Enum(AccessType, native_enum=False), nullable=False
    )

    # special info needed for the auto-sync feature. The exact structure depends on the

    # source type (defined in the connector's `source` field)
    # E.g. for google_drive perm sync:
    # {"customer_id": "123567", "company_domain": "@onyx.app"}
    auto_sync_options: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    last_time_perm_sync: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_time_external_group_sync: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Time finished, not used for calculating backend jobs which uses time started (created)
    last_successful_index_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # last successful prune
    last_pruned: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    total_docs_indexed: Mapped[int] = mapped_column(Integer, default=0)

    indexing_trigger: Mapped[IndexingMode | None] = mapped_column(
        Enum(IndexingMode, native_enum=False), nullable=True
    )

    connector: Mapped["Connector"] = relationship(
        "Connector", back_populates="credentials"
    )
    credential: Mapped["Credential"] = relationship(
        "Credential", back_populates="connectors"
    )
    document_sets: Mapped[list["DocumentSet"]] = relationship(
        "DocumentSet",
        secondary=DocumentSet__ConnectorCredentialPair.__table__,
        primaryjoin=(
            (DocumentSet__ConnectorCredentialPair.connector_credential_pair_id == id)
            & (DocumentSet__ConnectorCredentialPair.is_current.is_(True))
        ),
        back_populates="connector_credential_pairs",
        overlaps="document_set",
    )
    index_attempts: Mapped[list["IndexAttempt"]] = relationship(
        "IndexAttempt", back_populates="connector_credential_pair"
    )

    # the user id of the user that created this cc pair
    creator_id: Mapped[UUID | None] = mapped_column(nullable=True)
    creator: Mapped["User"] = relationship(
        "User",
        back_populates="cc_pairs",
        primaryjoin="foreign(ConnectorCredentialPair.creator_id) == remote(User.id)",
    )

    background_errors: Mapped[list["BackgroundError"]] = relationship(
        "BackgroundError", back_populates="cc_pair", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "document"
    # NOTE: if more sensitive data is added here for display, make sure to add user/group permission

    # this should correspond to the ID of the document
    # (as is passed around in Onyx)
    id: Mapped[str] = mapped_column(NullFilteredString, primary_key=True)
    from_ingestion_api: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=True
    )
    # 0 for neutral, positive for mostly endorse, negative for mostly reject
    boost: Mapped[int] = mapped_column(Integer, default=DEFAULT_BOOST)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_id: Mapped[str] = mapped_column(NullFilteredString)
    # First Section's link
    link: Mapped[str | None] = mapped_column(NullFilteredString, nullable=True)

    # The updated time is also used as a measure of the last successful state of the doc
    # pulled from the source (to help skip reindexing already updated docs in case of
    # connector retries)
    # TODO: rename this column because it conflates the time of the source doc
    # with the local last modified time of the doc and any associated metadata
    # it should just be the server timestamp of the source doc
    doc_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Number of chunks in the document (in Vespa)
    # Only null for documents indexed prior to this change
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # last time any vespa relevant row metadata or the doc changed.
    # does not include last_synced
    last_modified: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=func.now()
    )

    # last successful sync to vespa
    last_synced: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # The following are not attached to User because the account/email may not be known
    # within Onyx
    # Something like the document creator
    primary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    secondary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    # Permission sync columns
    # Email addresses are saved at the document level for externally synced permissions
    # This is becuase the normal flow of assigning permissions is through the cc_pair
    # doesn't apply here
    external_user_emails: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    # These group ids have been prefixed by the source type
    external_user_group_ids: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # tables for the knowledge graph data
    kg_stage: Mapped[KGStage] = mapped_column(
        Enum(KGStage, native_enum=False),
        comment="Status of knowledge graph extraction for this document",
        index=True,
    )

    kg_processing_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    retrieval_feedbacks: Mapped[list["DocumentRetrievalFeedback"]] = relationship(
        "DocumentRetrievalFeedback", back_populates="document"
    )

    doc_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(), nullable=True, default=None
    )
    tags = relationship(
        "Tag",
        secondary=Document__Tag.__table__,
        back_populates="documents",
    )

    __table_args__ = (
        Index(
            "ix_document_sync_status",
            last_modified,
            last_synced,
        ),
    )


class KGEntityType(Base):
    __tablename__ = "kg_entity_type"

    # Primary identifier
    id_name: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False, index=True
    )

    description: Mapped[str | None] = mapped_column(NullFilteredString, nullable=True)

    grounding: Mapped[str] = mapped_column(
        NullFilteredString, nullable=False, index=False
    )

    attributes: Mapped[dict | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
        default=dict,
        server_default="{}",
        comment="Filtering based on document attribute",
    )

    @property
    def parsed_attributes(self) -> KGEntityTypeAttributes:
        if self.attributes is None:
            return KGEntityTypeAttributes()

        try:
            return KGEntityTypeAttributes(**self.attributes)
        except ValidationError:
            return KGEntityTypeAttributes()

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    deep_extraction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Tracking fields
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    grounded_source_name: Mapped[str | None] = mapped_column(
        NullFilteredString, nullable=True, index=False
    )

    entity_values: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=True, default=None
    )

    clustering: Mapped[dict] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Clustering information for this entity type",
    )


class KGRelationshipType(Base):
    __tablename__ = "kg_relationship_type"

    # Primary identifier
    id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        primary_key=True,
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    source_entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    target_entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    definition: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this relationship type represents a definition",
    )

    clustering: Mapped[dict] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Clustering information for this relationship type",
    )

    type: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Tracking fields
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships to EntityType
    source_type: Mapped["KGEntityType"] = relationship(
        "KGEntityType",
        foreign_keys=[source_entity_type_id_name],
        backref="source_relationship_type",
    )
    target_type: Mapped["KGEntityType"] = relationship(
        "KGEntityType",
        foreign_keys=[target_entity_type_id_name],
        backref="target_relationship_type",
    )


class KGRelationshipTypeExtractionStaging(Base):
    __tablename__ = "kg_relationship_type_extraction_staging"

    # Primary identifier
    id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        primary_key=True,
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    source_entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    target_entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    definition: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this relationship type represents a definition",
    )

    clustering: Mapped[dict] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Clustering information for this relationship type",
    )

    type: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    transferred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # Tracking fields
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships to EntityType
    source_type: Mapped["KGEntityType"] = relationship(
        "KGEntityType",
        foreign_keys=[source_entity_type_id_name],
        backref="source_relationship_type_staging",
    )
    target_type: Mapped["KGEntityType"] = relationship(
        "KGEntityType",
        foreign_keys=[target_entity_type_id_name],
        backref="target_relationship_type_staging",
    )


class KGEntity(Base):
    __tablename__ = "kg_entity"

    # Primary identifier
    id_name: Mapped[str] = mapped_column(
        NullFilteredString, primary_key=True, index=True
    )

    # Basic entity information
    name: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )
    parent_key: Mapped[str | None] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )

    name_trigrams: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String(3)),
        nullable=True,
    )

    attributes: Mapped[dict] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Attributes for this entity",
    )

    document_id: Mapped[str | None] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )

    alternative_names: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    # Reference to KGEntityType
    entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    # Relationship to KGEntityType
    entity_type: Mapped["KGEntityType"] = relationship("KGEntityType", backref="entity")

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    keywords: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Access control
    acl: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    # Boosts - using JSON for flexibility
    boosts: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False, default=dict)

    event_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Time of the event being processed",
    )

    # Tracking fields
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Fixed column names in indexes
        Index("ix_entity_type_acl", entity_type_id_name, acl),
        Index("ix_entity_name_search", name, entity_type_id_name),
    )


class KGEntityExtractionStaging(Base):
    __tablename__ = "kg_entity_extraction_staging"

    # Primary identifier
    id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        primary_key=True,
        nullable=False,
        index=True,
    )

    # Basic entity information
    name: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    attributes: Mapped[dict] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Attributes for this entity",
    )

    document_id: Mapped[str | None] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )

    alternative_names: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    # Reference to KGEntityType
    entity_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    # Relationship to KGEntityType
    entity_type: Mapped["KGEntityType"] = relationship(
        "KGEntityType", backref="entity_staging"
    )

    description: Mapped[str | None] = mapped_column(String, nullable=True)

    keywords: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Access control
    acl: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    # Boosts - using JSON for flexibility
    boosts: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False, default=dict)

    transferred_id_name: Mapped[str | None] = mapped_column(
        NullFilteredString,
        nullable=True,
    )

    # Parent Child Information
    entity_key: Mapped[str] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )
    parent_key: Mapped[str | None] = mapped_column(
        NullFilteredString, nullable=True, index=True
    )

    event_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Time of the event being processed",
    )

    # Tracking fields
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Fixed column names in indexes
        Index("ix_entity_type_acl", entity_type_id_name, acl),
        Index("ix_entity_name_search", name, entity_type_id_name),
    )


class KGRelationship(Base):
    __tablename__ = "kg_relationship"

    # Primary identifier - now part of composite key
    id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        nullable=False,
        index=True,
    )

    source_document: Mapped[str | None] = mapped_column(
        NullFilteredString, ForeignKey("document.id"), nullable=True, index=True
    )

    # Source and target nodes (foreign keys to Entity table)
    source_node: Mapped[str] = mapped_column(
        NullFilteredString, ForeignKey("kg_entity.id_name"), nullable=False, index=True
    )

    target_node: Mapped[str] = mapped_column(
        NullFilteredString, ForeignKey("kg_entity.id_name"), nullable=False, index=True
    )

    source_node_type: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    target_node_type: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    # Relationship type
    type: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    # Add new relationship type reference
    relationship_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_relationship_type.id_name"),
        nullable=False,
        index=True,
    )

    # Add the SQLAlchemy relationship property
    relationship_type: Mapped["KGRelationshipType"] = relationship(
        "KGRelationshipType", backref="relationship"
    )

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Tracking fields
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships to Entity table
    source: Mapped["KGEntity"] = relationship("KGEntity", foreign_keys=[source_node])
    target: Mapped["KGEntity"] = relationship("KGEntity", foreign_keys=[target_node])
    document: Mapped["Document"] = relationship(
        "Document", foreign_keys=[source_document]
    )

    __table_args__ = (
        # Composite primary key
        PrimaryKeyConstraint("id_name", "source_document"),
        # Index for querying relationships by type
        Index("ix_kg_relationship_type", type),
        # Composite index for source/target queries
        Index("ix_kg_relationship_nodes", source_node, target_node),
        # Ensure unique relationships between nodes of a specific type
        UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
    )


class KGRelationshipExtractionStaging(Base):
    __tablename__ = "kg_relationship_extraction_staging"

    # Primary identifier - now part of composite key
    id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        nullable=False,
        index=True,
    )

    source_document: Mapped[str | None] = mapped_column(
        NullFilteredString, ForeignKey("document.id"), nullable=True, index=True
    )

    # Source and target nodes (foreign keys to Entity table)
    source_node: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_extraction_staging.id_name"),
        nullable=False,
        index=True,
    )

    target_node: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_extraction_staging.id_name"),
        nullable=False,
        index=True,
    )

    source_node_type: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    target_node_type: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_entity_type.id_name"),
        nullable=False,
        index=True,
    )

    # Relationship type
    type: Mapped[str] = mapped_column(NullFilteredString, nullable=False, index=True)

    # Add new relationship type reference
    relationship_type_id_name: Mapped[str] = mapped_column(
        NullFilteredString,
        ForeignKey("kg_relationship_type_extraction_staging.id_name"),
        nullable=False,
        index=True,
    )

    # Add the SQLAlchemy relationship property
    relationship_type: Mapped["KGRelationshipTypeExtractionStaging"] = relationship(
        "KGRelationshipTypeExtractionStaging", backref="relationship_staging"
    )

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    transferred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # Tracking fields
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships to Entity table
    source: Mapped["KGEntityExtractionStaging"] = relationship(
        "KGEntityExtractionStaging", foreign_keys=[source_node]
    )
    target: Mapped["KGEntityExtractionStaging"] = relationship(
        "KGEntityExtractionStaging", foreign_keys=[target_node]
    )
    document: Mapped["Document"] = relationship(
        "Document", foreign_keys=[source_document]
    )

    __table_args__ = (
        # Composite primary key
        PrimaryKeyConstraint("id_name", "source_document"),
        # Index for querying relationships by type
        Index("ix_kg_relationship_type", type),
        # Composite index for source/target queries
        Index("ix_kg_relationship_nodes", source_node, target_node),
        # Ensure unique relationships between nodes of a specific type
        UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
    )


class KGTerm(Base):
    __tablename__ = "kg_term"

    # Make id_term the primary key
    id_term: Mapped[str] = mapped_column(
        NullFilteredString, primary_key=True, nullable=False, index=True
    )

    # List of entity types this term applies to
    entity_types: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), nullable=False, default=list
    )

    # Tracking fields
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Index for searching terms with specific entity types
        Index("ix_search_term_entities", entity_types),
        # Index for term lookups
        Index("ix_search_term_term", id_term),
    )


class ChunkStats(Base):
    __tablename__ = "chunk_stats"
    # NOTE: if more sensitive data is added here for display, make sure to add user/group permission

    # this should correspond to the ID of the document
    # (as is passed around in Onyx)x
    id: Mapped[str] = mapped_column(
        NullFilteredString,
        primary_key=True,
        default=lambda context: (
            f"{context.get_current_parameters()['document_id']}"
            f"__{context.get_current_parameters()['chunk_in_doc_id']}"
        ),
        index=True,
    )

    # Reference to parent document
    document_id: Mapped[str] = mapped_column(
        NullFilteredString, ForeignKey("document.id"), nullable=False, index=True
    )

    chunk_in_doc_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    information_content_boost: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    last_modified: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=func.now()
    )
    last_synced: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        Index(
            "ix_chunk_sync_status",
            last_modified,
            last_synced,
        ),
        UniqueConstraint(
            "document_id", "chunk_in_doc_id", name="uq_chunk_stats_doc_chunk"
        ),
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_key: Mapped[str] = mapped_column(String)
    tag_value: Mapped[str] = mapped_column(String)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )
    is_list: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    documents = relationship(
        "Document",
        secondary=Document__Tag.__table__,
        back_populates="tags",
    )

    __table_args__ = (
        UniqueConstraint(
            "tag_key",
            "tag_value",
            "source",
            "is_list",
            name="_tag_key_value_source_list_uc",
        ),
    )


class Connector(Base):
    __tablename__ = "connector"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )
    input_type = mapped_column(Enum(InputType, native_enum=False))
    connector_specific_config: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB()
    )
    indexing_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    kg_processing_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this connector should extract knowledge graph entities",
    )

    kg_coverage_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    refresh_freq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prune_freq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    credentials: Mapped[list["ConnectorCredentialPair"]] = relationship(
        "ConnectorCredentialPair",
        back_populates="connector",
        cascade="all, delete-orphan",
    )
    documents_by_connector: Mapped[list["DocumentByConnectorCredentialPair"]] = (
        relationship(
            "DocumentByConnectorCredentialPair",
            back_populates="connector",
            passive_deletes=True,
        )
    )

    # synchronize this validation logic with RefreshFrequencySchema etc on front end
    # until we have a centralized validation schema

    # TODO(rkuo): experiment with SQLAlchemy validators rather than manual checks
    # https://docs.sqlalchemy.org/en/20/orm/mapped_attributes.html
    def validate_refresh_freq(self) -> None:
        if self.refresh_freq is not None:
            if self.refresh_freq < 60:
                raise ValueError(
                    "refresh_freq must be greater than or equal to 1 minute."
                )

    def validate_prune_freq(self) -> None:
        if self.prune_freq is not None:
            if self.prune_freq < 300:
                raise ValueError(
                    "prune_freq must be greater than or equal to 5 minutes."
                )


class Credential(Base):
    __tablename__ = "credential"

    name: Mapped[str] = mapped_column(String, nullable=True)

    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_json: Mapped[dict[str, Any]] = mapped_column(EncryptedJson())
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    # if `true`, then all Admins will have access to the credential
    admin_public: Mapped[bool] = mapped_column(Boolean, default=True)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    curator_public: Mapped[bool] = mapped_column(Boolean, default=False)

    connectors: Mapped[list["ConnectorCredentialPair"]] = relationship(
        "ConnectorCredentialPair",
        back_populates="credential",
        cascade="all, delete-orphan",
    )
    documents_by_credential: Mapped[list["DocumentByConnectorCredentialPair"]] = (
        relationship(
            "DocumentByConnectorCredentialPair",
            back_populates="credential",
            passive_deletes=True,
        )
    )

    user: Mapped[User | None] = relationship("User", back_populates="credentials")


class FederatedConnector(Base):
    __tablename__ = "federated_connector"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[FederatedConnectorSource] = mapped_column(
        Enum(FederatedConnectorSource, native_enum=False)
    )
    credentials: Mapped[dict[str, str]] = mapped_column(EncryptedJson(), nullable=False)

    oauth_tokens: Mapped[list["FederatedConnectorOAuthToken"]] = relationship(
        "FederatedConnectorOAuthToken",
        back_populates="federated_connector",
        cascade="all, delete-orphan",
    )
    document_sets: Mapped[list["FederatedConnector__DocumentSet"]] = relationship(
        "FederatedConnector__DocumentSet",
        back_populates="federated_connector",
        cascade="all, delete-orphan",
    )


class FederatedConnectorOAuthToken(Base):
    __tablename__ = "federated_connector_oauth_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    federated_connector_id: Mapped[int] = mapped_column(
        ForeignKey("federated_connector.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    federated_connector: Mapped["FederatedConnector"] = relationship(
        "FederatedConnector", back_populates="oauth_tokens"
    )
    user: Mapped["User"] = relationship("User")


class FederatedConnector__DocumentSet(Base):
    __tablename__ = "federated_connector__document_set"

    id: Mapped[int] = mapped_column(primary_key=True)
    federated_connector_id: Mapped[int] = mapped_column(
        ForeignKey("federated_connector.id", ondelete="CASCADE"), nullable=False
    )
    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id", ondelete="CASCADE"), nullable=False
    )
    # unique per source type. Validated before insertion.
    entities: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB(), nullable=False)

    federated_connector: Mapped["FederatedConnector"] = relationship(
        "FederatedConnector", back_populates="document_sets"
    )
    document_set: Mapped["DocumentSet"] = relationship(
        "DocumentSet", back_populates="federated_connectors"
    )

    __table_args__ = (
        UniqueConstraint(
            "federated_connector_id",
            "document_set_id",
            name="uq_federated_connector_document_set",
        ),
    )


class SearchSettings(Base):
    __tablename__ = "search_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String)
    model_dim: Mapped[int] = mapped_column(Integer)
    normalize: Mapped[bool] = mapped_column(Boolean)
    query_prefix: Mapped[str | None] = mapped_column(String, nullable=True)
    passage_prefix: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[IndexModelStatus] = mapped_column(
        Enum(IndexModelStatus, native_enum=False)
    )
    index_name: Mapped[str] = mapped_column(String)
    provider_type: Mapped[EmbeddingProvider | None] = mapped_column(
        ForeignKey("embedding_provider.provider_type"), nullable=True
    )

    # Whether switching to this model should re-index all connectors in the background
    # if no re-index is needed, will be ignored. Only used during the switch-over process.
    background_reindex_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # allows for quantization -> less memory usage for a small performance hit
    embedding_precision: Mapped[EmbeddingPrecision] = mapped_column(
        Enum(EmbeddingPrecision, native_enum=False)
    )

    # can be used to reduce dimensionality of vectors and save memory with
    # a small performance hit. More details in the `Reducing embedding dimensions`
    # section here:
    # https://platform.openai.com/docs/guides/embeddings#embedding-models
    # If not specified, will just use the model_dim without any reduction.
    # NOTE: this is only currently available for OpenAI models
    reduced_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Mini and Large Chunks (large chunk also checks for model max context)
    multipass_indexing: Mapped[bool] = mapped_column(Boolean, default=True)

    # Contextual RAG
    enable_contextual_rag: Mapped[bool] = mapped_column(Boolean, default=False)

    # Contextual RAG LLM
    contextual_rag_llm_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contextual_rag_llm_provider: Mapped[str | None] = mapped_column(
        String, nullable=True
    )

    multilingual_expansion: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String), default=[]
    )

    # Reranking settings
    disable_rerank_for_streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    rerank_model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    rerank_provider_type: Mapped[RerankerProvider | None] = mapped_column(
        Enum(RerankerProvider, native_enum=False), nullable=True
    )
    rerank_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    rerank_api_url: Mapped[str | None] = mapped_column(String, nullable=True)

    num_rerank: Mapped[int] = mapped_column(Integer, default=NUM_POSTPROCESSED_RESULTS)

    cloud_provider: Mapped["CloudEmbeddingProvider"] = relationship(
        "CloudEmbeddingProvider",
        back_populates="search_settings",
        foreign_keys=[provider_type],
    )

    index_attempts: Mapped[list["IndexAttempt"]] = relationship(
        "IndexAttempt", back_populates="search_settings"
    )

    __table_args__ = (
        Index(
            "ix_embedding_model_present_unique",
            "status",
            unique=True,
            postgresql_where=(status == IndexModelStatus.PRESENT),
        ),
        Index(
            "ix_embedding_model_future_unique",
            "status",
            unique=True,
            postgresql_where=(status == IndexModelStatus.FUTURE),
        ),
    )

    def __repr__(self) -> str:
        return f"<EmbeddingModel(model_name='{self.model_name}', status='{self.status}',\
          cloud_provider='{self.cloud_provider.provider_type if self.cloud_provider else 'None'}')>"

    @property
    def api_version(self) -> str | None:
        return (
            self.cloud_provider.api_version if self.cloud_provider is not None else None
        )

    @property
    def deployment_name(self) -> str | None:
        return (
            self.cloud_provider.deployment_name
            if self.cloud_provider is not None
            else None
        )

    @property
    def api_url(self) -> str | None:
        return self.cloud_provider.api_url if self.cloud_provider is not None else None

    @property
    def api_key(self) -> str | None:
        return self.cloud_provider.api_key if self.cloud_provider is not None else None

    @property
    def large_chunks_enabled(self) -> bool:
        """
        Given multipass usage and an embedder, decides whether large chunks are allowed
        based on model/provider constraints.
        """
        # Only local models that support a larger context are from Nomic
        # Cohere does not support larger contexts (they recommend not going above ~512 tokens)
        return SearchSettings.can_use_large_chunks(
            self.multipass_indexing, self.model_name, self.provider_type
        )

    @property
    def final_embedding_dim(self) -> int:
        return self.reduced_dimension or self.model_dim

    @staticmethod
    def can_use_large_chunks(
        multipass: bool, model_name: str, provider_type: EmbeddingProvider | None
    ) -> bool:
        """
        Given multipass usage and an embedder, decides whether large chunks are allowed
        based on model/provider constraints.
        """
        # Only local models that support a larger context are from Nomic
        # Cohere does not support larger contexts (they recommend not going above ~512 tokens)
        return (
            multipass
            and model_name.startswith("nomic-ai")
            and provider_type != EmbeddingProvider.COHERE
        )


class IndexAttempt(Base):
    """
    Represents an attempt to index a group of 0 or more documents from a
    source. For example, a single pull from Google Drive, a single event from
    slack event API, or a single website crawl.
    """

    __tablename__ = "index_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)

    connector_credential_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"),
        nullable=False,
    )

    # Some index attempts that run from beginning will still have this as False
    # This is only for attempts that are explicitly marked as from the start via
    # the run once API
    from_beginning: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[IndexingStatus] = mapped_column(
        Enum(IndexingStatus, native_enum=False, index=True)
    )
    # The two below may be slightly out of sync if user switches Embedding Model
    new_docs_indexed: Mapped[int | None] = mapped_column(Integer, default=0)
    total_docs_indexed: Mapped[int | None] = mapped_column(Integer, default=0)
    docs_removed_from_index: Mapped[int | None] = mapped_column(Integer, default=0)
    # only filled if status = "failed"
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    # only filled if status = "failed" AND an unhandled exception caused the failure
    full_exception_trace: Mapped[str | None] = mapped_column(Text, default=None)
    # Nullable because in the past, we didn't allow swapping out embedding models live
    search_settings_id: Mapped[int] = mapped_column(
        ForeignKey("search_settings.id", ondelete="SET NULL"),
        nullable=True,
    )

    # for polling connectors, the start and end time of the poll window
    # will be set when the index attempt starts
    poll_range_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    poll_range_end: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Points to the last checkpoint that was saved for this run. The pointer here
    # can be taken to the FileStore to grab the actual checkpoint value
    checkpoint_pointer: Mapped[str | None] = mapped_column(String, nullable=True)

    # Database-based coordination fields (replacing Redis fencing)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    # Batch coordination fields
    # Once this is set, docfetching has completed
    total_batches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # batches that are fully indexed (i.e. have completed docfetching and docprocessing)
    completed_batches: Mapped[int] = mapped_column(Integer, default=0)
    # TODO: unused, remove this column
    total_failures_batch_level: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)

    # Progress tracking for stall detection
    last_progress_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_batches_completed_count: Mapped[int] = mapped_column(Integer, default=0)

    # Heartbeat tracking for worker liveness detection
    heartbeat_counter: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat_value: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    # when the actual indexing run began
    # NOTE: will use the api_server clock rather than DB server clock
    time_started: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    connector_credential_pair: Mapped[ConnectorCredentialPair] = relationship(
        "ConnectorCredentialPair", back_populates="index_attempts"
    )

    search_settings: Mapped[SearchSettings | None] = relationship(
        "SearchSettings", back_populates="index_attempts"
    )

    error_rows = relationship(
        "IndexAttemptError",
        back_populates="index_attempt",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "ix_index_attempt_latest_for_connector_credential_pair",
            "connector_credential_pair_id",
            "time_created",
        ),
        Index(
            "ix_index_attempt_ccpair_search_settings_time_updated",
            "connector_credential_pair_id",
            "search_settings_id",
            desc("time_updated"),
            unique=False,
        ),
        Index(
            "ix_index_attempt_cc_pair_settings_poll",
            "connector_credential_pair_id",
            "search_settings_id",
            "status",
            desc("time_updated"),
        ),
        # NEW: Index for coordination queries
        Index(
            "ix_index_attempt_active_coordination",
            "connector_credential_pair_id",
            "search_settings_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<IndexAttempt(id={self.id!r}, "
            f"status={self.status!r}, "
            f"error_msg={self.error_msg!r})>"
            f"time_created={self.time_created!r}, "
            f"time_updated={self.time_updated!r}, "
        )

    def is_finished(self) -> bool:
        return self.status.is_terminal()

    def is_coordination_complete(self) -> bool:
        """Check if all batches have been processed"""
        return (
            self.total_batches is not None
            and self.completed_batches >= self.total_batches
        )


class IndexAttemptError(Base):
    __tablename__ = "index_attempt_errors"

    id: Mapped[int] = mapped_column(primary_key=True)

    index_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("index_attempt.id"),
        nullable=False,
    )
    connector_credential_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"),
        nullable=False,
    )

    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    document_link: Mapped[str | None] = mapped_column(String, nullable=True)

    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    failed_time_range_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_time_range_end: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    failure_message: Mapped[str] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # This is the reverse side of the relationship
    index_attempt = relationship("IndexAttempt", back_populates="error_rows")


class SyncRecord(Base):
    """
    Represents the status of a "sync" operation (e.g. document set, user group, deletion).

    A "sync" operation is an operation which needs to update a set of documents within
    Vespa, usually to match the state of Postgres.
    """

    __tablename__ = "sync_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # document set id, user group id, or deletion id
    entity_id: Mapped[int] = mapped_column(Integer)

    sync_type: Mapped[SyncType] = mapped_column(Enum(SyncType, native_enum=False))
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, native_enum=False))

    num_docs_synced: Mapped[int] = mapped_column(Integer, default=0)

    sync_start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    sync_end_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_sync_record_entity_id_sync_type_sync_start_time",
            "entity_id",
            "sync_type",
            "sync_start_time",
        ),
        Index(
            "ix_sync_record_entity_id_sync_type_sync_status",
            "entity_id",
            "sync_type",
            "sync_status",
        ),
    )


class DocumentByConnectorCredentialPair(Base):
    """Represents an indexing of a document by a specific connector / credential pair"""

    __tablename__ = "document_by_connector_credential_pair"

    id: Mapped[str] = mapped_column(ForeignKey("document.id"), primary_key=True)
    # TODO: transition this to use the ConnectorCredentialPair id directly
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("connector.id", ondelete="CASCADE"), primary_key=True
    )
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credential.id", ondelete="CASCADE"), primary_key=True
    )

    # used to better keep track of document counts at a connector level
    # e.g. if a document is added as part of permission syncing, it should
    # not be counted as part of the connector's document count until
    # the actual indexing is complete
    has_been_indexed: Mapped[bool] = mapped_column(Boolean)

    connector: Mapped[Connector] = relationship(
        "Connector", back_populates="documents_by_connector", passive_deletes=True
    )
    credential: Mapped[Credential] = relationship(
        "Credential", back_populates="documents_by_credential", passive_deletes=True
    )

    __table_args__ = (
        Index(
            "idx_document_cc_pair_connector_credential",
            "connector_id",
            "credential_id",
            unique=False,
        ),
        # Index to optimize get_document_counts_for_cc_pairs query pattern
        Index(
            "idx_document_cc_pair_counts",
            "connector_id",
            "credential_id",
            "has_been_indexed",
            unique=False,
        ),
    )


"""
Messages Tables
"""


class SearchDoc(Base):
    """Different from Document table. This one stores the state of a document from a retrieval.
    This allows chat sessions to be replayed with the searched docs

    Notably, this does not include the contents of the Document/Chunk, during inference if a stored
    SearchDoc is selected, an inference must be remade to retrieve the contents
    """

    __tablename__ = "search_doc"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String)
    chunk_ind: Mapped[int] = mapped_column(Integer)
    semantic_id: Mapped[str] = mapped_column(String)
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    blurb: Mapped[str] = mapped_column(String)
    boost: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )
    hidden: Mapped[bool] = mapped_column(Boolean)
    doc_metadata: Mapped[dict[str, str | list[str]]] = mapped_column(postgresql.JSONB())
    score: Mapped[float] = mapped_column(Float)
    match_highlights: Mapped[list[str]] = mapped_column(postgresql.ARRAY(String))
    # This is for the document, not this row in the table
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    primary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    secondary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    is_internet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)

    is_relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    relevance_explanation: Mapped[str | None] = mapped_column(String, nullable=True)

    chat_messages = relationship(
        "ChatMessage",
        secondary=ChatMessage__SearchDoc.__table__,
        back_populates="search_docs",
    )
    sub_queries = relationship(
        "AgentSubQuery",
        secondary=AgentSubQuery__SearchDoc.__table__,
        back_populates="search_docs",
    )


class ToolCall(Base):
    """Represents a single tool call"""

    __tablename__ = "tool_call"

    id: Mapped[int] = mapped_column(primary_key=True)
    # not a FK because we want to be able to delete the tool without deleting
    # this entry
    tool_id: Mapped[int] = mapped_column(Integer())
    tool_name: Mapped[str] = mapped_column(String())
    tool_arguments: Mapped[dict[str, JSON_ro]] = mapped_column(postgresql.JSONB())
    tool_result: Mapped[JSON_ro] = mapped_column(postgresql.JSONB())

    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_message.id"), nullable=False
    )

    # Update the relationship
    message: Mapped["ChatMessage"] = relationship(
        "ChatMessage",
        back_populates="tool_call",
        uselist=False,
    )


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("persona.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # This chat created by OnyxBot
    onyxbot_flow: Mapped[bool] = mapped_column(Boolean, default=False)
    # Only ever set to True if system is set to not hard-delete chats
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    # controls whether or not this conversation is viewable by others
    shared_status: Mapped[ChatSessionSharedStatus] = mapped_column(
        Enum(ChatSessionSharedStatus, native_enum=False),
        default=ChatSessionSharedStatus.PRIVATE,
    )

    current_alternate_model: Mapped[str | None] = mapped_column(String, default=None)

    slack_thread_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_project.id"), nullable=True
    )

    project: Mapped["UserProject"] = relationship(
        "UserProject", back_populates="chat_sessions", foreign_keys=[project_id]
    )

    # the latest "overrides" specified by the user. These take precedence over
    # the attached persona. However, overrides specified directly in the
    # `send-message` call will take precedence over these.
    # NOTE: currently only used by the chat seeding flow, will be used in the
    # future once we allow users to override default values via the Chat UI
    # itself
    llm_override: Mapped[LLMOverride | None] = mapped_column(
        PydanticType(LLMOverride), nullable=True
    )

    # The latest temperature override specified by the user
    temperature_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    prompt_override: Mapped[PromptOverride | None] = mapped_column(
        PydanticType(PromptOverride), nullable=True
    )
    time_updated: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user: Mapped[User] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="chat_session", cascade="all, delete-orphan"
    )
    persona: Mapped["Persona"] = relationship("Persona")


class ChatMessage(Base):
    """Note, the first message in a chain has no contents, it's a workaround to allow edits
    on the first message of a session, an empty root node basically

    Since every user message is followed by a LLM response, chat messages generally come in pairs.
    Keeping them as separate messages however for future Agentification extensions
    Fields will be largely duplicated in the pair.
    """

    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_session.id")
    )

    alternate_assistant_id = mapped_column(
        Integer, ForeignKey("persona.id"), nullable=True
    )

    overridden_model: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_message: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_child_message: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    rephrased_query: Mapped[str] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer)
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, native_enum=False)
    )
    # Maps the citation numbers to a SearchDoc id
    citations: Mapped[dict[int, int]] = mapped_column(postgresql.JSONB(), nullable=True)
    # files associated with this message (e.g. images uploaded by the user that the
    # user is asking a question of)
    files: Mapped[list[FileDescriptor] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    # Only applies for LLM
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_sent: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    is_agentic: Mapped[bool] = mapped_column(Boolean, default=False)
    refined_answer_improvement: Mapped[bool] = mapped_column(Boolean, nullable=True)

    chat_session: Mapped[ChatSession] = relationship("ChatSession")

    chat_message_feedbacks: Mapped[list["ChatMessageFeedback"]] = relationship(
        "ChatMessageFeedback",
        back_populates="chat_message",
    )

    document_feedbacks: Mapped[list["DocumentRetrievalFeedback"]] = relationship(
        "DocumentRetrievalFeedback",
        back_populates="chat_message",
    )
    search_docs: Mapped[list["SearchDoc"]] = relationship(
        "SearchDoc",
        secondary=ChatMessage__SearchDoc.__table__,
        back_populates="chat_messages",
        cascade="all, delete-orphan",
        single_parent=True,
    )

    tool_call: Mapped["ToolCall"] = relationship(
        "ToolCall",
        back_populates="message",
        uselist=False,
    )

    sub_questions: Mapped[list["AgentSubQuestion"]] = relationship(
        "AgentSubQuestion",
        back_populates="primary_message",
        order_by="(AgentSubQuestion.level, AgentSubQuestion.level_question_num)",
    )

    research_iterations: Mapped[list["ResearchAgentIteration"]] = relationship(
        "ResearchAgentIteration",
        foreign_keys="ResearchAgentIteration.primary_question_id",
        cascade="all, delete-orphan",
    )

    standard_answers: Mapped[list["StandardAnswer"]] = relationship(
        "StandardAnswer",
        secondary=ChatMessage__StandardAnswer.__table__,
        back_populates="chat_messages",
    )

    research_type: Mapped[ResearchType] = mapped_column(
        Enum(ResearchType, native_enum=False), nullable=True
    )
    research_plan: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)
    research_answer_purpose: Mapped[ResearchAnswerPurpose] = mapped_column(
        Enum(ResearchAnswerPurpose, native_enum=False), nullable=True
    )


class AgentSubQuestion(Base):
    """
    A sub-question is a question that is asked of the LLM to gather supporting
    information to answer a primary question.
    """

    __tablename__ = "agent__sub_question"

    id: Mapped[int] = mapped_column(primary_key=True)
    primary_question_id: Mapped[int] = mapped_column(
        ForeignKey("chat_message.id", ondelete="CASCADE")
    )
    chat_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_session.id")
    )
    sub_question: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    level_question_num: Mapped[int] = mapped_column(Integer)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sub_answer: Mapped[str] = mapped_column(Text)
    sub_question_doc_results: Mapped[JSON_ro] = mapped_column(postgresql.JSONB())

    # Relationships
    primary_message: Mapped["ChatMessage"] = relationship(
        "ChatMessage",
        foreign_keys=[primary_question_id],
        back_populates="sub_questions",
    )
    chat_session: Mapped["ChatSession"] = relationship("ChatSession")
    sub_queries: Mapped[list["AgentSubQuery"]] = relationship(
        "AgentSubQuery", back_populates="parent_question"
    )


class AgentSubQuery(Base):
    """
    A sub-query is a vector DB query that gathers supporting information to answer a sub-question.
    """

    __tablename__ = "agent__sub_query"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_question_id: Mapped[int] = mapped_column(
        ForeignKey("agent__sub_question.id", ondelete="CASCADE")
    )
    chat_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_session.id")
    )
    sub_query: Mapped[str] = mapped_column(Text)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    parent_question: Mapped["AgentSubQuestion"] = relationship(
        "AgentSubQuestion", back_populates="sub_queries"
    )
    chat_session: Mapped["ChatSession"] = relationship("ChatSession")
    search_docs: Mapped[list["SearchDoc"]] = relationship(
        "SearchDoc",
        secondary=AgentSubQuery__SearchDoc.__table__,
        back_populates="sub_queries",
    )


"""
Feedback, Logging, Metrics Tables
"""


class DocumentRetrievalFeedback(Base):
    __tablename__ = "document_retrieval_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_message.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    # How high up this document is in the results, 1 for first
    document_rank: Mapped[int] = mapped_column(Integer)
    clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[SearchFeedbackType | None] = mapped_column(
        Enum(SearchFeedbackType, native_enum=False), nullable=True
    )

    chat_message: Mapped[ChatMessage] = relationship(
        "ChatMessage",
        back_populates="document_feedbacks",
        foreign_keys=[chat_message_id],
    )
    document: Mapped[Document] = relationship(
        "Document", back_populates="retrieval_feedbacks"
    )


class ChatMessageFeedback(Base):
    __tablename__ = "chat_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_message.id", ondelete="SET NULL"), nullable=True
    )
    is_positive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    required_followup: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    predefined_feedback: Mapped[str | None] = mapped_column(String, nullable=True)

    chat_message: Mapped[ChatMessage] = relationship(
        "ChatMessage",
        back_populates="chat_message_feedbacks",
        foreign_keys=[chat_message_id],
    )


class LLMProvider(Base):
    __tablename__ = "llm_provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    provider: Mapped[str] = mapped_column(String)
    api_key: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    api_base: Mapped[str | None] = mapped_column(String, nullable=True)
    api_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # custom configs that should be passed to the LLM provider at inference time
    # (e.g. `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, etc. for bedrock)
    custom_config: Mapped[dict[str, str] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    default_model_name: Mapped[str] = mapped_column(String)
    fast_default_model_name: Mapped[str | None] = mapped_column(String, nullable=True)

    deployment_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # should only be set for a single provider
    is_default_provider: Mapped[bool | None] = mapped_column(Boolean, unique=True)
    is_default_vision_provider: Mapped[bool | None] = mapped_column(Boolean)
    default_vision_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # EE only
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="llm_provider__user_group",
        viewonly=True,
    )
    model_configurations: Mapped[list["ModelConfiguration"]] = relationship(
        "ModelConfiguration",
        back_populates="llm_provider",
        foreign_keys="ModelConfiguration.llm_provider_id",
    )


class ModelConfiguration(Base):
    __tablename__ = "model_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    llm_provider_id: Mapped[int] = mapped_column(
        ForeignKey("llm_provider.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Represents whether or not a given model will be usable by the end user or not.
    # This field is primarily used for "Well Known LLM Providers", since for them,
    # we have a pre-defined list of LLM models that we allow them to choose from.
    # For example, for OpenAI, we allow the end-user to choose multiple models from
    # `["gpt-4", "gpt-4o", etc.]`. Once they make their selections, we set each
    # selected model to `is_visible = True`.
    #
    # For "Custom LLM Providers", we don't provide a comprehensive list of models
    # for the end-user to choose from; *they provide it themselves*. Therefore,
    # for Custom LLM Providers, `is_visible` will always be True.
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Max input tokens can be null when:
    # - The end-user configures models through a "Well Known LLM Provider".
    # - The end-user is configuring a model and chooses not to set a max-input-tokens limit.
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    supports_image_input: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    llm_provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider",
        back_populates="model_configurations",
    )


class CloudEmbeddingProvider(Base):
    __tablename__ = "embedding_provider"

    provider_type: Mapped[EmbeddingProvider] = mapped_column(
        Enum(EmbeddingProvider), primary_key=True
    )
    api_url: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key: Mapped[str | None] = mapped_column(EncryptedString())
    api_version: Mapped[str | None] = mapped_column(String, nullable=True)
    deployment_name: Mapped[str | None] = mapped_column(String, nullable=True)

    search_settings: Mapped[list["SearchSettings"]] = relationship(
        "SearchSettings",
        back_populates="cloud_provider",
    )

    def __repr__(self) -> str:
        return f"<EmbeddingProvider(type='{self.provider_type}')>"


class DocumentSet(Base):
    __tablename__ = "document_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(String)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    # Whether changes to the document set have been propagated
    is_up_to_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # If `False`, then the document set is not visible to users who are not explicitly
    # given access to it either via the `users` or `groups` relationships
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Last time a user updated this document set
    time_last_modified_by_user: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    connector_credential_pairs: Mapped[list[ConnectorCredentialPair]] = relationship(
        "ConnectorCredentialPair",
        secondary=DocumentSet__ConnectorCredentialPair.__table__,
        primaryjoin=(
            (DocumentSet__ConnectorCredentialPair.document_set_id == id)
            & (DocumentSet__ConnectorCredentialPair.is_current.is_(True))
        ),
        secondaryjoin=(
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == ConnectorCredentialPair.id
        ),
        back_populates="document_sets",
        overlaps="document_set",
    )
    personas: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__DocumentSet.__table__,
        back_populates="document_sets",
    )
    # Other users with access
    users: Mapped[list[User]] = relationship(
        "User",
        secondary=DocumentSet__User.__table__,
        viewonly=True,
    )
    # EE only
    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="document_set__user_group",
        viewonly=True,
    )
    federated_connectors: Mapped[list["FederatedConnector__DocumentSet"]] = (
        relationship(
            "FederatedConnector__DocumentSet",
            back_populates="document_set",
            cascade="all, delete-orphan",
        )
    )


class Tool(Base):
    __tablename__ = "tool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    # ID of the tool in the codebase, only applies for in-code tools.
    # tools defined via the UI will have this as None
    in_code_tool_id: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String, nullable=True)

    # OpenAPI scheme for the tool. Only applies to tools defined via the UI.
    openapi_schema: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    # MCP tool input schema. Only applies to MCP tools.
    mcp_input_schema: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    custom_headers: Mapped[list[HeaderItemDict] | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    # user who created / owns the tool. Will be None for built-in tools.
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    # whether to pass through the user's OAuth token as Authorization header
    passthrough_auth: Mapped[bool] = mapped_column(Boolean, default=False)
    # MCP server this tool is associated with (null for non-MCP tools)
    mcp_server_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User | None] = relationship("User", back_populates="custom_tools")
    # Relationship to Persona through the association table
    personas: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__Tool.__table__,
        back_populates="tools",
    )
    # MCP server relationship
    mcp_server: Mapped["MCPServer | None"] = relationship(
        "MCPServer", back_populates="current_actions"
    )


class StarterMessage(BaseModel):
    """Starter message for a persona."""

    name: str
    message: str


class Persona__PersonaLabel(Base):
    __tablename__ = "persona__persona_label"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    persona_label_id: Mapped[int] = mapped_column(
        ForeignKey("persona_label.id", ondelete="CASCADE"), primary_key=True
    )


class Persona(Base):
    __tablename__ = "persona"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    # Number of chunks to pass to the LLM for generation.
    num_chunks: Mapped[float | None] = mapped_column(Float, nullable=True)
    chunks_above: Mapped[int] = mapped_column(Integer)
    chunks_below: Mapped[int] = mapped_column(Integer)
    # Pass every chunk through LLM for evaluation, fairly expensive
    # Can be turned off globally by admin, in which case, this setting is ignored
    llm_relevance_filter: Mapped[bool] = mapped_column(Boolean)
    # Enables using LLM to extract time and source type filters
    # Can also be admin disabled globally
    llm_filter_extraction: Mapped[bool] = mapped_column(Boolean)
    recency_bias: Mapped[RecencyBiasSetting] = mapped_column(
        Enum(RecencyBiasSetting, native_enum=False)
    )

    # Allows the Persona to specify a different LLM version than is controlled
    # globablly via env variables. For flexibility, validity is not currently enforced
    # NOTE: only is applied on the actual response generation - is not used for things like
    # auto-detected time filters, relevance filters, etc.
    llm_model_provider_override: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    llm_model_version_override: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    starter_messages: Mapped[list[StarterMessage] | None] = mapped_column(
        PydanticListType(StarterMessage), nullable=True
    )
    search_start_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Built-in personas are configured via backend during deployment
    # Treated specially (cannot be user edited etc.)
    builtin_persona: Mapped[bool] = mapped_column(Boolean, default=False)

    # Default personas are personas created by admins and are automatically added
    # to all users' assistants list.
    is_default_persona: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # controls whether the persona is available to be selected by users
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    # controls the ordering of personas in the UI
    # higher priority personas are displayed first, ties are resolved by the ID,
    # where lower value IDs (e.g. created earlier) are displayed first
    display_priority: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Prompt fields merged from Prompt table
    system_prompt: Mapped[str | None] = mapped_column(
        String(length=PROMPT_LENGTH), nullable=True
    )
    task_prompt: Mapped[str | None] = mapped_column(
        String(length=PROMPT_LENGTH), nullable=True
    )
    datetime_aware: Mapped[bool] = mapped_column(Boolean, default=True)

    uploaded_image_id: Mapped[str | None] = mapped_column(String, nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String, nullable=True)
    icon_shape: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # These are only defaults, users can select from all if desired
    document_sets: Mapped[list[DocumentSet]] = relationship(
        "DocumentSet",
        secondary=Persona__DocumentSet.__table__,
        back_populates="personas",
    )
    tools: Mapped[list[Tool]] = relationship(
        "Tool",
        secondary=Persona__Tool.__table__,
        back_populates="personas",
    )
    # Owner
    user: Mapped[User | None] = relationship("User", back_populates="personas")
    # Other users with access
    users: Mapped[list[User]] = relationship(
        "User",
        secondary=Persona__User.__table__,
        viewonly=True,
    )
    # EE only
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="persona__user_group",
        viewonly=True,
    )
    # Relationship to UserFile
    user_files: Mapped[list["UserFile"]] = relationship(
        "UserFile",
        secondary="persona__user_file",
        back_populates="assistants",
    )
    labels: Mapped[list["PersonaLabel"]] = relationship(
        "PersonaLabel",
        secondary=Persona__PersonaLabel.__table__,
        back_populates="personas",
    )

    # Default personas loaded via yaml cannot have the same name
    __table_args__ = (
        Index(
            "_builtin_persona_name_idx",
            "name",
            unique=True,
            postgresql_where=(builtin_persona == True),  # noqa: E712
        ),
    )


class Persona__UserFile(Base):
    __tablename__ = "persona__user_file"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    user_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_file.id"), primary_key=True
    )


class PersonaLabel(Base):
    __tablename__ = "persona_label"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    personas: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__PersonaLabel.__table__,
        back_populates="labels",
        cascade="all, delete-orphan",
        single_parent=True,
    )


class Assistant__UserSpecificConfig(Base):
    __tablename__ = "assistant__user_specific_config"

    assistant_id: Mapped[int] = mapped_column(
        ForeignKey("persona.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    disabled_tool_ids: Mapped[list[int]] = mapped_column(
        postgresql.ARRAY(Integer), nullable=False
    )


AllowedAnswerFilters = (
    Literal["well_answered_postfilter"] | Literal["questionmark_prefilter"]
)


class ChannelConfig(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    channel_name: str | None  # None for default channel config
    respond_tag_only: NotRequired[bool]  # defaults to False
    respond_to_bots: NotRequired[bool]  # defaults to False
    is_ephemeral: NotRequired[bool]  # defaults to False
    respond_member_group_list: NotRequired[list[str]]
    answer_filters: NotRequired[list[AllowedAnswerFilters]]
    # If None then no follow up
    # If empty list, follow up with no tags
    follow_up_tags: NotRequired[list[str]]
    show_continue_in_web_ui: NotRequired[bool]  # defaults to False
    disabled: NotRequired[bool]  # defaults to False


class SlackChannelConfig(Base):
    __tablename__ = "slack_channel_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    slack_bot_id: Mapped[int] = mapped_column(
        ForeignKey("slack_bot.id"), nullable=False
    )
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("persona.id"), nullable=True
    )
    channel_config: Mapped[ChannelConfig] = mapped_column(
        postgresql.JSONB(), nullable=False
    )

    enable_auto_filters: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    persona: Mapped[Persona | None] = relationship("Persona")

    slack_bot: Mapped["SlackBot"] = relationship(
        "SlackBot",
        back_populates="slack_channel_configs",
    )
    standard_answer_categories: Mapped[list["StandardAnswerCategory"]] = relationship(
        "StandardAnswerCategory",
        secondary=SlackChannelConfig__StandardAnswerCategory.__table__,
        back_populates="slack_channel_configs",
    )

    __table_args__ = (
        UniqueConstraint(
            "slack_bot_id",
            "is_default",
            name="uq_slack_channel_config_slack_bot_id_default",
        ),
        Index(
            "ix_slack_channel_config_slack_bot_id_default",
            "slack_bot_id",
            "is_default",
            unique=True,
            postgresql_where=(is_default is True),  #   type: ignore
        ),
    )


class SlackBot(Base):
    __tablename__ = "slack_bot"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    bot_token: Mapped[str] = mapped_column(EncryptedString(), unique=True)
    app_token: Mapped[str] = mapped_column(EncryptedString(), unique=True)
    user_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    slack_channel_configs: Mapped[list[SlackChannelConfig]] = relationship(
        "SlackChannelConfig",
        back_populates="slack_bot",
        cascade="all, delete-orphan",
    )


class Milestone(Base):
    # This table is used to track significant events for a deployment towards finding value
    # The table is currently not used for features but it may be used in the future to inform
    # users about the product features and encourage usage/exploration.
    __tablename__ = "milestone"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[MilestoneRecordType] = mapped_column(String)
    # Need to track counts and specific ids of certain events to know if the Milestone has been reached
    event_tracker: Mapped[dict | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship("User")

    __table_args__ = (UniqueConstraint("event_type", name="uq_milestone_event_type"),)


class TaskQueueState(Base):
    # Currently refers to Celery Tasks
    __tablename__ = "task_queue_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Celery task id. currently only for readability/diagnostics
    task_id: Mapped[str] = mapped_column(String)
    # For any job type, this would be the same
    task_name: Mapped[str] = mapped_column(String)
    # Note that if the task dies, this won't necessarily be marked FAILED correctly
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, native_enum=False))
    start_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    register_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KVStore(Base):
    __tablename__ = "key_value_store"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)
    encrypted_value: Mapped[JSON_ro] = mapped_column(EncryptedJson(), nullable=True)


class FileRecord(Base):
    __tablename__ = "file_record"

    # Internal file ID, must be unique across all files.
    file_id: Mapped[str] = mapped_column(String, primary_key=True)

    display_name: Mapped[str] = mapped_column(String, nullable=True)
    file_origin: Mapped[FileOrigin] = mapped_column(Enum(FileOrigin, native_enum=False))
    file_type: Mapped[str] = mapped_column(String, default="text/plain")
    file_metadata: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)

    # External storage support (S3, MinIO, Azure Blob, etc.)
    bucket_name: Mapped[str] = mapped_column(String)
    object_key: Mapped[str] = mapped_column(String)

    # Timestamps for external storage
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentSearchMetrics(Base):
    __tablename__ = "agent__search_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("persona.id"), nullable=True
    )
    agent_type: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    base_duration_s: Mapped[float] = mapped_column(Float)
    full_duration_s: Mapped[float] = mapped_column(Float)
    base_metrics: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)
    refined_metrics: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)
    all_metrics: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)


"""
************************************************************************
Enterprise Edition Models
************************************************************************

These models are only used in Enterprise Edition only features in Onyx.
They are kept here to simplify the codebase and avoid having different assumptions
on the shape of data being passed around between the MIT and EE versions of Onyx.

In the MIT version of Onyx, assume these tables are always empty.
"""


class SamlAccount(Base):
    __tablename__ = "saml"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), unique=True
    )
    encrypted_cookie: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User")


class User__UserGroup(Base):
    __tablename__ = "user__user_group"

    is_curator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, nullable=True
    )


class UserGroup__ConnectorCredentialPair(Base):
    __tablename__ = "user_group__connector_credential_pair"

    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )
    cc_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"), primary_key=True
    )
    # if `True`, then is part of the current state of the UserGroup
    # if `False`, then is a part of the prior state of the UserGroup
    # rows with `is_current=False` should be deleted when the UserGroup
    # is updated and should not exist for a given UserGroup if
    # `UserGroup.is_up_to_date == True`
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        primary_key=True,
    )

    cc_pair: Mapped[ConnectorCredentialPair] = relationship(
        "ConnectorCredentialPair",
    )


class Persona__UserGroup(Base):
    __tablename__ = "persona__user_group"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class LLMProvider__UserGroup(Base):
    __tablename__ = "llm_provider__user_group"

    llm_provider_id: Mapped[int] = mapped_column(
        ForeignKey("llm_provider.id"), primary_key=True
    )
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class DocumentSet__UserGroup(Base):
    __tablename__ = "document_set__user_group"

    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id"), primary_key=True
    )
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class Credential__UserGroup(Base):
    __tablename__ = "credential__user_group"

    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credential.id"), primary_key=True
    )
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class UserGroup(Base):
    __tablename__ = "user_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    # whether or not changes to the UserGroup have been propagated to Vespa
    is_up_to_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # tell the sync job to clean up the group
    is_up_for_deletion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Last time a user updated this user group
    time_last_modified_by_user: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    users: Mapped[list[User]] = relationship(
        "User",
        secondary=User__UserGroup.__table__,
    )
    user_group_relationships: Mapped[list[User__UserGroup]] = relationship(
        "User__UserGroup",
        viewonly=True,
    )
    cc_pairs: Mapped[list[ConnectorCredentialPair]] = relationship(
        "ConnectorCredentialPair",
        secondary=UserGroup__ConnectorCredentialPair.__table__,
        viewonly=True,
    )
    cc_pair_relationships: Mapped[list[UserGroup__ConnectorCredentialPair]] = (
        relationship(
            "UserGroup__ConnectorCredentialPair",
            viewonly=True,
        )
    )
    personas: Mapped[list[Persona]] = relationship(
        "Persona",
        secondary=Persona__UserGroup.__table__,
        viewonly=True,
    )
    document_sets: Mapped[list[DocumentSet]] = relationship(
        "DocumentSet",
        secondary=DocumentSet__UserGroup.__table__,
        viewonly=True,
    )
    credentials: Mapped[list[Credential]] = relationship(
        "Credential",
        secondary=Credential__UserGroup.__table__,
    )
    # MCP servers accessible to this user group
    accessible_mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer", secondary="mcp_server__user_group", back_populates="user_groups"
    )


"""Tables related to Token Rate Limiting
NOTE: `TokenRateLimit` is partially an MIT feature (global rate limit)
"""


class TokenRateLimit(Base):
    __tablename__ = "token_rate_limit"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    period_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[TokenRateLimitScope] = mapped_column(
        Enum(TokenRateLimitScope, native_enum=False)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TokenRateLimit__UserGroup(Base):
    __tablename__ = "token_rate_limit__user_group"

    rate_limit_id: Mapped[int] = mapped_column(
        ForeignKey("token_rate_limit.id"), primary_key=True
    )
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class StandardAnswerCategory(Base):
    __tablename__ = "standard_answer_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    standard_answers: Mapped[list["StandardAnswer"]] = relationship(
        "StandardAnswer",
        secondary=StandardAnswer__StandardAnswerCategory.__table__,
        back_populates="categories",
    )
    slack_channel_configs: Mapped[list["SlackChannelConfig"]] = relationship(
        "SlackChannelConfig",
        secondary=SlackChannelConfig__StandardAnswerCategory.__table__,
        back_populates="standard_answer_categories",
    )


class StandardAnswer(Base):
    __tablename__ = "standard_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String)
    answer: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean)
    match_regex: Mapped[bool] = mapped_column(Boolean)
    match_any_keywords: Mapped[bool] = mapped_column(Boolean)

    __table_args__ = (
        Index(
            "unique_keyword_active",
            keyword,
            active,
            unique=True,
            postgresql_where=(active == True),  # noqa: E712
        ),
    )

    categories: Mapped[list[StandardAnswerCategory]] = relationship(
        "StandardAnswerCategory",
        secondary=StandardAnswer__StandardAnswerCategory.__table__,
        back_populates="standard_answers",
    )
    chat_messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        secondary=ChatMessage__StandardAnswer.__table__,
        back_populates="standard_answers",
    )


class BackgroundError(Base):
    """Important background errors. Serves to:
    1. Ensure that important logs are kept around and not lost on rotation/container restarts
    2. A trail for high-signal events so that the debugger doesn't need to remember/know every
       possible relevant log line.
    """

    __tablename__ = "background_error"

    id: Mapped[int] = mapped_column(primary_key=True)
    message: Mapped[str] = mapped_column(String)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # option to link the error to a specific CC Pair
    cc_pair_id: Mapped[int | None] = mapped_column(
        ForeignKey("connector_credential_pair.id", ondelete="CASCADE"), nullable=True
    )

    cc_pair: Mapped["ConnectorCredentialPair | None"] = relationship(
        "ConnectorCredentialPair", back_populates="background_errors"
    )


"""Tables related to Permission Sync"""


class User__ExternalUserGroupId(Base):
    """Maps user info both internal and external to the name of the external group
    This maps the user to all of their external groups so that the external group name can be
    attached to the ACL list matching during query time. User level permissions can be handled by
    directly adding the Onyx user to the doc ACL list"""

    __tablename__ = "user__external_user_group_id"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)
    # These group ids have been prefixed by the source type
    external_user_group_id: Mapped[str] = mapped_column(String, primary_key=True)
    cc_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"), primary_key=True
    )

    # Signifies whether or not the group should be cleaned up at the end of a
    # group sync run.
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index(
            "ix_user_external_group_cc_pair_stale",
            "cc_pair_id",
            "stale",
        ),
        Index(
            "ix_user_external_group_stale",
            "stale",
        ),
    )


class PublicExternalUserGroup(Base):
    """Stores all public external user "groups".

    For example, things like Google Drive folders that are marked
    as `Anyone with the link` or `Anyone in the domain`
    """

    __tablename__ = "public_external_user_group"

    external_user_group_id: Mapped[str] = mapped_column(String, primary_key=True)
    cc_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id", ondelete="CASCADE"), primary_key=True
    )

    # Signifies whether or not the group should be cleaned up at the end of a
    # group sync run.
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index(
            "ix_public_external_group_cc_pair_stale",
            "cc_pair_id",
            "stale",
        ),
        Index(
            "ix_public_external_group_stale",
            "stale",
        ),
    )


class UsageReport(Base):
    """This stores metadata about usage reports generated by admin including user who generated
    them as well as the period they cover. The actual zip file of the report is stored as a lo
    using the FileRecord
    """

    __tablename__ = "usage_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_name: Mapped[str] = mapped_column(ForeignKey("file_record.file_id"))

    # if None, report was auto-generated
    requestor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    period_from: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    period_to: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    requestor = relationship("User")
    file = relationship("FileRecord")


class InputPrompt(Base):
    __tablename__ = "inputprompt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean)
    user: Mapped[User | None] = relationship("User", back_populates="input_prompts")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )


class InputPrompt__User(Base):
    __tablename__ = "inputprompt__user"

    input_prompt_id: Mapped[int] = mapped_column(
        ForeignKey("inputprompt.id"), primary_key=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inputprompt.id"), primary_key=True
    )
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Project__UserFile(Base):
    __tablename__ = "project__user_file"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("user_project.id"), primary_key=True
    )
    user_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_file.id"), primary_key=True
    )


class UserProject(Base):
    __tablename__ = "user_project"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user: Mapped["User"] = relationship(back_populates="projects")
    user_files: Mapped[list["UserFile"]] = relationship(
        "UserFile",
        secondary=Project__UserFile.__table__,
        back_populates="projects",
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="project", lazy="selectin"
    )
    instructions: Mapped[str] = mapped_column(String)


class UserDocument(str, Enum):
    CHAT = "chat"
    RECENT = "recent"
    FILE = "file"


class UserFile(Base):
    __tablename__ = "user_file"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=False)
    assistants: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__UserFile.__table__,
        back_populates="user_files",
    )
    file_id: Mapped[str] = mapped_column(nullable=False)
    document_id: Mapped[str] = mapped_column(
        nullable=False
    )  # TODO(subash): legacy document_id, will be removed in a future migration
    name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
    user: Mapped["User"] = relationship(back_populates="files")
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    file_type: Mapped[str] = mapped_column(String, nullable=False)

    status: Mapped[UserFileStatus] = mapped_column(
        Enum(UserFileStatus, native_enum=False, name="userfilestatus"),
        nullable=False,
        default=UserFileStatus.PROCESSING,
    )
    needs_project_sync: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_project_sync_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_accessed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    link_url: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    document_id_migrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    projects: Mapped[list["UserProject"]] = relationship(
        "UserProject",
        secondary=Project__UserFile.__table__,
        back_populates="user_files",
        lazy="selectin",
    )


"""
Multi-tenancy related tables
"""


class PublicBase(DeclarativeBase):
    __abstract__ = True


# Strictly keeps track of the tenant that a given user will authenticate to.
class UserTenantMapping(Base):
    __tablename__ = "user_tenant_mapping"
    __table_args__ = ({"schema": "public"},)

    email: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @validates("email")
    def validate_email(self, key: str, value: str) -> str:
        return value.lower() if value else value


class AvailableTenant(Base):
    __tablename__ = "available_tenant"
    """
    These entries will only exist ephemerally and are meant to be picked up by new users on registration.
    """

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    alembic_version: Mapped[str] = mapped_column(String, nullable=False)
    date_created: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)


# This is a mapping from tenant IDs to anonymous user paths
class TenantAnonymousUserPath(Base):
    __tablename__ = "tenant_anonymous_user_path"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    anonymous_user_path: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )


class ResearchAgentIteration(Base):
    __tablename__ = "research_agent_iteration"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    primary_question_id: Mapped[int] = mapped_column(
        ForeignKey("chat_message.id", ondelete="CASCADE")
    )
    iteration_nr: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String, nullable=True)

    reasoning: Mapped[str] = mapped_column(String, nullable=True)

    # Relationships
    primary_message: Mapped["ChatMessage"] = relationship(
        "ChatMessage",
        foreign_keys=[primary_question_id],
        back_populates="research_iterations",
    )

    sub_steps: Mapped[list["ResearchAgentIterationSubStep"]] = relationship(
        "ResearchAgentIterationSubStep",
        primaryjoin=(
            "and_("
            "ResearchAgentIteration.primary_question_id == ResearchAgentIterationSubStep.primary_question_id, "
            "ResearchAgentIteration.iteration_nr == ResearchAgentIterationSubStep.iteration_nr"
            ")"
        ),
        foreign_keys="[ResearchAgentIterationSubStep.primary_question_id, ResearchAgentIterationSubStep.iteration_nr]",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "primary_question_id",
            "iteration_nr",
            name="_research_agent_iteration_unique_constraint",
        ),
    )


class ResearchAgentIterationSubStep(Base):
    __tablename__ = "research_agent_iteration_sub_step"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    primary_question_id: Mapped[int] = mapped_column(Integer, nullable=False)

    iteration_nr: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration_sub_step_nr: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sub_step_instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_step_tool_id: Mapped[int | None] = mapped_column(
        ForeignKey("tool.id", ondelete="SET NULL"), nullable=True
    )

    # for all step-types
    reasoning: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_answer: Mapped[str | None] = mapped_column(String, nullable=True)

    # for search-based step-types
    cited_doc_results: Mapped[JSON_ro] = mapped_column(postgresql.JSONB())
    claims: Mapped[list[str] | None] = mapped_column(postgresql.JSONB(), nullable=True)
    is_web_fetch: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    queries: Mapped[list[str] | None] = mapped_column(postgresql.JSONB(), nullable=True)

    # for image generation step-types
    generated_images: Mapped[GeneratedImageFullResult | None] = mapped_column(
        PydanticType(GeneratedImageFullResult), nullable=True
    )

    # for custom step-types
    additional_data: Mapped[JSON_ro | None] = mapped_column(
        postgresql.JSONB(), nullable=True
    )

    # Relationships
    # Note: ChatMessage is accessible via primary_question_id. It is tied to the
    # primary_question_id in research_agent_iteration, which has a foreign key constraint
    # to ChatMessage.id.

    __table_args__ = (
        ForeignKeyConstraint(
            ["primary_question_id", "iteration_nr"],
            [
                "research_agent_iteration.primary_question_id",
                "research_agent_iteration.iteration_nr",
            ],
            ondelete="CASCADE",
        ),
    )


class MCPServer(Base):
    """Model for storing MCP server configurations"""

    __tablename__ = "mcp_server"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Owner email of user who configured this server
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    server_url: Mapped[str] = mapped_column(String, nullable=False)
    # Transport type for connecting to the MCP server
    transport: Mapped[MCPTransport] = mapped_column(
        Enum(MCPTransport, native_enum=False), nullable=False
    )
    # Auth type: "none", "api_token", or "oauth"
    auth_type: Mapped[MCPAuthenticationType] = mapped_column(
        Enum(MCPAuthenticationType, native_enum=False), nullable=False
    )
    # Who performs authentication for this server (ADMIN or PER_USER)
    auth_performer: Mapped[MCPAuthenticationPerformer] = mapped_column(
        Enum(MCPAuthenticationPerformer, native_enum=False), nullable=False
    )
    # Admin connection config - used for the config page
    # and (when applicable) admin-managed auth
    # and (when applicable) per-user auth
    admin_connection_config_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("mcp_connection_config.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    admin_connection_config: Mapped["MCPConnectionConfig | None"] = relationship(
        "MCPConnectionConfig",
        foreign_keys=[admin_connection_config_id],
        back_populates="admin_servers",
    )

    user_connection_configs: Mapped[list["MCPConnectionConfig"]] = relationship(
        "MCPConnectionConfig",
        foreign_keys="MCPConnectionConfig.mcp_server_id",
        back_populates="mcp_server",
    )
    current_actions: Mapped[list["Tool"]] = relationship(
        "Tool", back_populates="mcp_server", cascade="all, delete-orphan"
    )
    # Many-to-many relationships for access control
    users: Mapped[list["User"]] = relationship(
        "User", secondary="mcp_server__user", back_populates="accessible_mcp_servers"
    )
    user_groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="mcp_server__user_group",
        back_populates="accessible_mcp_servers",
    )


class MCPServer__User(Base):
    __tablename__ = "mcp_server__user"
    mcp_server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_server.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )


class MCPServer__UserGroup(Base):
    __tablename__ = "mcp_server__user_group"
    mcp_server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_server.id"), primary_key=True
    )
    user_group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), primary_key=True
    )


class MCPConnectionConfig(Base):
    """Model for storing MCP connection configurations (credentials, auth data)"""

    __tablename__ = "mcp_connection_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Server this config is for (nullable for template configs)
    mcp_server_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=True
    )
    # User email this config is for (empty for admin configs and templates)
    user_email: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Config data stored as JSON
    # Format: {
    #   "refresh_token": "<token>",  # OAuth only
    #   "access_token": "<token>",   # OAuth only
    #   "headers": {"key": "value", "key2": "value2"},
    #   "header_substitutions": {"<key>": "<value>"}, # stored header template substitutions
    #   "request_body": ["path/in/body:value", "path2/in2/body2:value2"] # TBD
    #   "client_id": "<id>",  # For dynamically registered OAuth clients
    #   "client_secret": "<secret>",  # For confidential clients
    #   "registration_access_token": "<token>",  # For managing registration
    #   "registration_client_uri": "<uri>",  # For managing registration
    # }
    config: Mapped[MCPConnectionData] = mapped_column(
        EncryptedJson(), nullable=False, default=dict
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    mcp_server: Mapped["MCPServer | None"] = relationship(
        "MCPServer",
        foreign_keys=[mcp_server_id],
        back_populates="user_connection_configs",
    )
    admin_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer",
        foreign_keys="MCPServer.admin_connection_config_id",
        back_populates="admin_connection_config",
    )

    __table_args__ = (
        Index("ix_mcp_connection_config_user_email", "user_email"),
        Index("ix_mcp_connection_config_server_user", "mcp_server_id", "user_email"),
    )


"""
Permission Sync Tables
"""


class DocPermissionSyncAttempt(Base):
    """
    Represents an attempt to sync document permissions for a connector credential pair.
    Similar to IndexAttempt but specifically for document permission syncing operations.
    """

    __tablename__ = "doc_permission_sync_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)

    connector_credential_pair_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credential_pair.id"),
        nullable=False,
    )

    # Status of the sync attempt
    status: Mapped[PermissionSyncStatus] = mapped_column(
        Enum(PermissionSyncStatus, native_enum=False, index=True)
    )

    # Counts for tracking progress
    total_docs_synced: Mapped[int | None] = mapped_column(Integer, default=0)
    docs_with_permission_errors: Mapped[int | None] = mapped_column(Integer, default=0)

    # Error message if sync fails
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    # Timestamps
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    time_started: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    time_finished: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Relationships
    connector_credential_pair: Mapped[ConnectorCredentialPair] = relationship(
        "ConnectorCredentialPair"
    )

    __table_args__ = (
        Index(
            "ix_permission_sync_attempt_latest_for_cc_pair",
            "connector_credential_pair_id",
            "time_created",
        ),
        Index(
            "ix_permission_sync_attempt_status_time",
            "status",
            desc("time_finished"),
        ),
    )

    def __repr__(self) -> str:
        return f"<DocPermissionSyncAttempt(id={self.id!r}, " f"status={self.status!r})>"

    def is_finished(self) -> bool:
        return self.status.is_terminal()


class ExternalGroupPermissionSyncAttempt(Base):
    """
    Represents an attempt to sync external group memberships for users.
    This tracks the syncing of user-to-external-group mappings across connectors.
    """

    __tablename__ = "external_group_permission_sync_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Can be tied to a specific connector or be a global group sync
    connector_credential_pair_id: Mapped[int | None] = mapped_column(
        ForeignKey("connector_credential_pair.id"),
        nullable=True,  # Nullable for global group syncs across all connectors
    )

    # Status of the group sync attempt
    status: Mapped[PermissionSyncStatus] = mapped_column(
        Enum(PermissionSyncStatus, native_enum=False, index=True)
    )

    # Counts for tracking progress
    total_users_processed: Mapped[int | None] = mapped_column(Integer, default=0)
    total_groups_processed: Mapped[int | None] = mapped_column(Integer, default=0)
    total_group_memberships_synced: Mapped[int | None] = mapped_column(
        Integer, default=0
    )

    # Error message if sync fails
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    # Timestamps
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    time_started: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    time_finished: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Relationships
    connector_credential_pair: Mapped[ConnectorCredentialPair | None] = relationship(
        "ConnectorCredentialPair"
    )

    __table_args__ = (
        Index(
            "ix_group_sync_attempt_cc_pair_time",
            "connector_credential_pair_id",
            "time_created",
        ),
        Index(
            "ix_group_sync_attempt_status_time",
            "status",
            desc("time_finished"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ExternalGroupPermissionSyncAttempt(id={self.id!r}, "
            f"status={self.status!r})>"
        )

    def is_finished(self) -> bool:
        return self.status.is_terminal()
