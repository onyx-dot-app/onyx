import datetime
import json
from enum import Enum as PyEnum
from typing import Any
from typing import Literal
from typing import NotRequired
from typing import Optional
from typing import TypedDict
from uuid import UUID

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseOAuthAccountTableUUID
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import TIMESTAMPAware
from sqlalchemy import Boolean
from sqlalchemy import DateTime
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

from danswer.auth.schemas import UserRole
from danswer.configs.constants import DEFAULT_BOOST
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import FileOrigin
from danswer.configs.constants import MessageType
from danswer.configs.constants import NotificationType
from danswer.configs.constants import SearchFeedbackType
from danswer.configs.constants import TokenRateLimitScope
from danswer.connectors.models import InputType
from danswer.db.enums import ChatSessionSharedStatus
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.enums import IndexingStatus
from danswer.db.enums import IndexModelStatus
from danswer.db.enums import TaskStatus
from danswer.db.pydantic_type import PydanticType
from danswer.dynamic_configs.interface import JSON_ro
from danswer.file_store.models import FileDescriptor
from danswer.llm.override_models import LLMOverride
from danswer.llm.override_models import PromptOverride
from danswer.search.enums import RecencyBiasSetting
from danswer.utils.encryption import decrypt_bytes_to_string
from danswer.utils.encryption import encrypt_string_to_bytes
from shared_configs.enums import EmbeddingProvider


class Base(DeclarativeBase):
    pass


class EncryptedString(TypeDecorator):
    impl = LargeBinary

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


"""
Auth/Authz (users, permissions, access) Tables
"""


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    # even an almost empty token from keycloak will not fit the default 1024 bytes
    access_token: Mapped[str] = mapped_column(Text, nullable=False)  # type: ignore


class User(SQLAlchemyBaseUserTableUUID, Base):
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined"
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, default=UserRole.BASIC)
    )

    """
    Preferences probably should be in a separate table at some point, but for now
    putting here for simpicity
    """

    # if specified, controls the assistants that are shown to the user + their order
    # if not specified, all assistants are shown
    chosen_assistants: Mapped[list[int]] = mapped_column(
        postgresql.JSONB(), nullable=True
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
    chat_folders: Mapped[list["ChatFolder"]] = relationship(
        "ChatFolder", back_populates="user"
    )

    prompts: Mapped[list["Prompt"]] = relationship("Prompt", back_populates="user")
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


class InputPrompt(Base):
    __tablename__ = "inputprompt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean)
    user: Mapped[User | None] = relationship("User", back_populates="input_prompts")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)


class InputPrompt__User(Base):
    __tablename__ = "inputprompt__user"

    input_prompt_id: Mapped[int] = mapped_column(
        ForeignKey("inputprompt.id"), primary_key=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inputprompt.id"), primary_key=True
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    pass


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
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_shown: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    first_shown: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="notifications")


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


class Persona__Prompt(Base):
    __tablename__ = "persona__prompt"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompt.id"), primary_key=True)


class Persona__User(Base):
    __tablename__ = "persona__user"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id"), primary_key=True, nullable=True
    )


class DocumentSet__User(Base):
    __tablename__ = "document_set__user"

    document_set_id: Mapped[int] = mapped_column(
        ForeignKey("document_set.id"), primary_key=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id"), primary_key=True, nullable=True
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


class Document__Tag(Base):
    __tablename__ = "document__tag"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class Persona__Tool(Base):
    __tablename__ = "persona__tool"

    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"), primary_key=True)
    tool_id: Mapped[int] = mapped_column(ForeignKey("tool.id"), primary_key=True)


class StandardAnswer__StandardAnswerCategory(Base):
    __tablename__ = "standard_answer__standard_answer_category"

    standard_answer_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer.id"), primary_key=True
    )
    standard_answer_category_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer_category.id"), primary_key=True
    )


class SlackBotConfig__StandardAnswerCategory(Base):
    __tablename__ = "slack_bot_config__standard_answer_category"

    slack_bot_config_id: Mapped[int] = mapped_column(
        ForeignKey("slack_bot_config.id"), primary_key=True
    )
    standard_answer_category_id: Mapped[int] = mapped_column(
        ForeignKey("standard_answer_category.id"), primary_key=True
    )


class ChatMessage__StandardAnswer(Base):
    __tablename__ = "chat_message__standard_answer"

    chat_message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_message.id"), primary_key=True
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
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("connector.id"), primary_key=True
    )
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credential.id"), primary_key=True
    )
    # controls whether the documents indexed by this CC pair are visible to all
    # or if they are only visible to those with that are given explicit access
    # (e.g. via owning the credential or being a part of a group that is given access)
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    # Time finished, not used for calculating backend jobs which uses time started (created)
    last_successful_index_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    total_docs_indexed: Mapped[int] = mapped_column(Integer, default=0)

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


class Document(Base):
    __tablename__ = "document"

    # this should correspond to the ID of the document
    # (as is passed around in Danswer)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_ingestion_api: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=True
    )
    # 0 for neutral, positive for mostly endorse, negative for mostly reject
    boost: Mapped[int] = mapped_column(Integer, default=DEFAULT_BOOST)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_id: Mapped[str] = mapped_column(String)
    # First Section's link
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    # The updated time is also used as a measure of the last successful state of the doc
    # pulled from the source (to help skip reindexing already updated docs in case of
    # connector retries)
    doc_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The following are not attached to User because the account/email may not be known
    # within Danswer
    # Something like the document creator
    primary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    secondary_owners: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    # TODO if more sensitive data is added here for display, make sure to add user/group permission

    retrieval_feedbacks: Mapped[list["DocumentRetrievalFeedback"]] = relationship(
        "DocumentRetrievalFeedback", back_populates="document"
    )
    tags = relationship(
        "Tag",
        secondary="document__tag",
        back_populates="documents",
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_key: Mapped[str] = mapped_column(String)
    tag_value: Mapped[str] = mapped_column(String)
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )

    documents = relationship(
        "Document",
        secondary="document__tag",
        back_populates="tags",
    )

    __table_args__ = (
        UniqueConstraint(
            "tag_key", "tag_value", "source", name="_tag_key_value_source_uc"
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
    documents_by_connector: Mapped[
        list["DocumentByConnectorCredentialPair"]
    ] = relationship("DocumentByConnectorCredentialPair", back_populates="connector")


class Credential(Base):
    __tablename__ = "credential"

    name: Mapped[str] = mapped_column(String, nullable=True)

    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_json: Mapped[dict[str, Any]] = mapped_column(EncryptedJson())
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
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
    documents_by_credential: Mapped[
        list["DocumentByConnectorCredentialPair"]
    ] = relationship("DocumentByConnectorCredentialPair", back_populates="credential")

    user: Mapped[User | None] = relationship("User", back_populates="credentials")


class EmbeddingModel(Base):
    __tablename__ = "embedding_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String)
    model_dim: Mapped[int] = mapped_column(Integer)
    normalize: Mapped[bool] = mapped_column(Boolean)
    query_prefix: Mapped[str] = mapped_column(String)
    passage_prefix: Mapped[str] = mapped_column(String)
    status: Mapped[IndexModelStatus] = mapped_column(
        Enum(IndexModelStatus, native_enum=False)
    )
    index_name: Mapped[str] = mapped_column(String)

    # New field for cloud provider relationship
    provider_type: Mapped[EmbeddingProvider | None] = mapped_column(
        ForeignKey("embedding_provider.provider_type"), nullable=True
    )

    cloud_provider: Mapped["CloudEmbeddingProvider"] = relationship(
        "CloudEmbeddingProvider",
        back_populates="embedding_models",
        foreign_keys=[provider_type],
    )

    index_attempts: Mapped[list["IndexAttempt"]] = relationship(
        "IndexAttempt", back_populates="embedding_model"
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
    def api_key(self) -> str | None:
        return self.cloud_provider.api_key if self.cloud_provider is not None else None


class IndexAttempt(Base):
    """
    Represents an attempt to index a group of 1 or more documents from a
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
        Enum(IndexingStatus, native_enum=False)
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
    embedding_model_id: Mapped[int] = mapped_column(
        ForeignKey("embedding_model.id"),
        nullable=False,
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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

    embedding_model: Mapped[EmbeddingModel] = relationship(
        "EmbeddingModel", back_populates="index_attempts"
    )

    error_rows = relationship("IndexAttemptError", back_populates="index_attempt")

    __table_args__ = (
        Index(
            "ix_index_attempt_latest_for_connector_credential_pair",
            "connector_credential_pair_id",
            "time_created",
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


class IndexAttemptError(Base):
    """
    Represents an error that was encountered during an IndexAttempt.
    """

    __tablename__ = "index_attempt_errors"

    id: Mapped[int] = mapped_column(primary_key=True)

    index_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("index_attempt.id"),
        nullable=True,
    )

    # The index of the batch where the error occurred (if looping thru batches)
    # Just informational.
    batch: Mapped[int | None] = mapped_column(Integer, default=None)
    doc_summaries: Mapped[list[Any]] = mapped_column(postgresql.JSONB())
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    traceback: Mapped[str | None] = mapped_column(Text, default=None)
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # This is the reverse side of the relationship
    index_attempt = relationship("IndexAttempt", back_populates="error_rows")

    __table_args__ = (
        Index(
            "index_attempt_id",
            "time_created",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<IndexAttempt(id={self.id!r}, "
            f"index_attempt_id={self.index_attempt_id!r}, "
            f"error_msg={self.error_msg!r})>"
            f"time_created={self.time_created!r}, "
        )


class DocumentByConnectorCredentialPair(Base):
    """Represents an indexing of a document by a specific connector / credential pair"""

    __tablename__ = "document_by_connector_credential_pair"

    id: Mapped[str] = mapped_column(ForeignKey("document.id"), primary_key=True)
    # TODO: transition this to use the ConnectorCredentialPair id directly
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("connector.id"), primary_key=True
    )
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credential.id"), primary_key=True
    )

    connector: Mapped[Connector] = relationship(
        "Connector", back_populates="documents_by_connector"
    )
    credential: Mapped[Credential] = relationship(
        "Credential", back_populates="documents_by_credential"
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
        secondary="chat_message__search_doc",
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

    message_id: Mapped[int] = mapped_column(ForeignKey("chat_message.id"))

    message: Mapped["ChatMessage"] = relationship(
        "ChatMessage", back_populates="tool_calls"
    )


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("persona.id"))
    description: Mapped[str] = mapped_column(Text)
    # One-shot direct answering, currently the two types of chats are not mixed
    one_shot: Mapped[bool] = mapped_column(Boolean, default=False)
    danswerbot_flow: Mapped[bool] = mapped_column(Boolean, default=False)
    # Only ever set to True if system is set to not hard-delete chats
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    # controls whether or not this conversation is viewable by others
    shared_status: Mapped[ChatSessionSharedStatus] = mapped_column(
        Enum(ChatSessionSharedStatus, native_enum=False),
        default=ChatSessionSharedStatus.PRIVATE,
    )
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_folder.id"), nullable=True
    )

    current_alternate_model: Mapped[str | None] = mapped_column(String, default=None)

    slack_thread_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
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
    folder: Mapped["ChatFolder"] = relationship(
        "ChatFolder", back_populates="chat_sessions"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="chat_session"
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
    chat_session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id"))

    alternate_assistant_id = mapped_column(
        Integer, ForeignKey("persona.id"), nullable=True
    )

    overridden_model: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_message: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_child_message: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    rephrased_query: Mapped[str] = mapped_column(Text, nullable=True)
    # If None, then there is no answer generation, it's the special case of only
    # showing the user the retrieved docs
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompt.id"))
    # If prompt is None, then token_count is 0 as this message won't be passed into
    # the LLM's context (not included in the history of messages)
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

    chat_session: Mapped[ChatSession] = relationship("ChatSession")
    prompt: Mapped[Optional["Prompt"]] = relationship("Prompt")

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
        secondary="chat_message__search_doc",
        back_populates="chat_messages",
    )
    # NOTE: Should always be attached to the `assistant` message.
    # represents the tool calls used to generate this message
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall",
        back_populates="message",
    )
    standard_answers: Mapped[list["StandardAnswer"]] = relationship(
        "StandardAnswer",
        secondary=ChatMessage__StandardAnswer.__table__,
        back_populates="chat_messages",
    )


class ChatFolder(Base):
    """For organizing chat sessions"""

    __tablename__ = "chat_folder"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Only null if auth is off
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    display_priority: Mapped[int] = mapped_column(Integer, nullable=True, default=0)

    user: Mapped[User] = relationship("User", back_populates="chat_folders")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="folder"
    )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, ChatFolder):
            return NotImplemented
        if self.display_priority == other.display_priority:
            # Bigger ID (created later) show earlier
            return self.id > other.id
        return self.display_priority < other.display_priority


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

    # Models to actually disp;aly to users
    # If nulled out, we assume in the application logic we should present all
    display_model_names: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )
    # The LLMs that are available for this provider. Only required if not a default provider.
    # If a default provider, then the LLM options are pulled from the `options.py` file.
    # If needed, can be pulled out as a separate table in the future.
    model_names: Mapped[list[str] | None] = mapped_column(
        postgresql.ARRAY(String), nullable=True
    )

    # should only be set for a single provider
    is_default_provider: Mapped[bool | None] = mapped_column(Boolean, unique=True)
    # EE only
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        secondary="llm_provider__user_group",
        viewonly=True,
    )


class CloudEmbeddingProvider(Base):
    __tablename__ = "embedding_provider"

    provider_type: Mapped[EmbeddingProvider] = mapped_column(
        Enum(EmbeddingProvider), primary_key=True
    )
    api_key: Mapped[str | None] = mapped_column(EncryptedString())
    embedding_models: Mapped[list["EmbeddingModel"]] = relationship(
        "EmbeddingModel",
        back_populates="cloud_provider",
        foreign_keys="EmbeddingModel.provider_type",
    )

    def __repr__(self) -> str:
        return f"<EmbeddingProvider(type='{self.provider_type}')>"


class DocumentSet(Base):
    __tablename__ = "document_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(String)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    # Whether changes to the document set have been propagated
    is_up_to_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # If `False`, then the document set is not visible to users who are not explicitly
    # given access to it either via the `users` or `groups` relationships
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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


class Prompt(Base):
    __tablename__ = "prompt"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    system_prompt: Mapped[str] = mapped_column(Text)
    task_prompt: Mapped[str] = mapped_column(Text)
    include_citations: Mapped[bool] = mapped_column(Boolean, default=True)
    datetime_aware: Mapped[bool] = mapped_column(Boolean, default=True)
    # Default prompts are configured via backend during deployment
    # Treated specially (cannot be user edited etc.)
    default_prompt: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship("User", back_populates="prompts")
    personas: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__Prompt.__table__,
        back_populates="prompts",
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

    # user who created / owns the tool. Will be None for built-in tools.
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)

    user: Mapped[User | None] = relationship("User", back_populates="custom_tools")
    # Relationship to Persona through the association table
    personas: Mapped[list["Persona"]] = relationship(
        "Persona",
        secondary=Persona__Tool.__table__,
        back_populates="tools",
    )


class StarterMessage(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    name: str
    description: str
    message: str


class Persona(Base):
    __tablename__ = "persona"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
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
        postgresql.JSONB(), nullable=True
    )
    # Default personas are configured via backend during deployment
    # Treated specially (cannot be user edited etc.)
    default_persona: Mapped[bool] = mapped_column(Boolean, default=False)
    # controls whether the persona is available to be selected by users
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    # controls the ordering of personas in the UI
    # higher priority personas are displayed first, ties are resolved by the ID,
    # where lower value IDs (e.g. created earlier) are displayed first
    display_priority: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    uploaded_image_id: Mapped[str | None] = mapped_column(String, nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String, nullable=True)
    icon_shape: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # These are only defaults, users can select from all if desired
    prompts: Mapped[list[Prompt]] = relationship(
        "Prompt",
        secondary=Persona__Prompt.__table__,
        back_populates="personas",
    )
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

    # Default personas loaded via yaml cannot have the same name
    __table_args__ = (
        Index(
            "_default_persona_name_idx",
            "name",
            unique=True,
            postgresql_where=(default_persona == True),  # noqa: E712
        ),
    )


AllowedAnswerFilters = (
    Literal["well_answered_postfilter"] | Literal["questionmark_prefilter"]
)


class ChannelConfig(TypedDict):
    """NOTE: is a `TypedDict` so it can be used as a type hint for a JSONB column
    in Postgres"""

    channel_names: list[str]
    respond_tag_only: NotRequired[bool]  # defaults to False
    respond_to_bots: NotRequired[bool]  # defaults to False
    respond_member_group_list: NotRequired[list[str]]
    answer_filters: NotRequired[list[AllowedAnswerFilters]]
    # If None then no follow up
    # If empty list, follow up with no tags
    follow_up_tags: NotRequired[list[str]]


class StandardAnswerCategory(Base):
    __tablename__ = "standard_answer_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    standard_answers: Mapped[list["StandardAnswer"]] = relationship(
        "StandardAnswer",
        secondary=StandardAnswer__StandardAnswerCategory.__table__,
        back_populates="categories",
    )
    slack_bot_configs: Mapped[list["SlackBotConfig"]] = relationship(
        "SlackBotConfig",
        secondary=SlackBotConfig__StandardAnswerCategory.__table__,
        back_populates="standard_answer_categories",
    )


class StandardAnswer(Base):
    __tablename__ = "standard_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String)
    answer: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean)

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


class SlackBotResponseType(str, PyEnum):
    QUOTES = "quotes"
    CITATIONS = "citations"


class SlackBotConfig(Base):
    __tablename__ = "slack_bot_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("persona.id"), nullable=True
    )
    # JSON for flexibility. Contains things like: channel name, team members, etc.
    channel_config: Mapped[ChannelConfig] = mapped_column(
        postgresql.JSONB(), nullable=False
    )
    response_type: Mapped[SlackBotResponseType] = mapped_column(
        Enum(SlackBotResponseType, native_enum=False), nullable=False
    )

    enable_auto_filters: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    persona: Mapped[Persona | None] = relationship("Persona")
    standard_answer_categories: Mapped[list[StandardAnswerCategory]] = relationship(
        "StandardAnswerCategory",
        secondary=SlackBotConfig__StandardAnswerCategory.__table__,
        back_populates="slack_bot_configs",
    )


class TaskQueueState(Base):
    # Currently refers to Celery Tasks
    __tablename__ = "task_queue_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Celery task id
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


class PGFileStore(Base):
    __tablename__ = "file_store"

    file_name: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=True)
    file_origin: Mapped[FileOrigin] = mapped_column(Enum(FileOrigin, native_enum=False))
    file_type: Mapped[str] = mapped_column(String, default="text/plain")
    file_metadata: Mapped[JSON_ro] = mapped_column(postgresql.JSONB(), nullable=True)
    lobj_oid: Mapped[int] = mapped_column(Integer, nullable=False)


"""
************************************************************************
Enterprise Edition Models
************************************************************************

These models are only used in Enterprise Edition only features in Danswer.
They are kept here to simplify the codebase and avoid having different assumptions
on the shape of data being passed around between the MIT and EE versions of Danswer.

In the MIT version of Danswer, assume these tables are always empty.
"""


class SamlAccount(Base):
    __tablename__ = "saml"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
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
        ForeignKey("user.id"), primary_key=True, nullable=True
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
    cc_pair_relationships: Mapped[
        list[UserGroup__ConnectorCredentialPair]
    ] = relationship(
        "UserGroup__ConnectorCredentialPair",
        viewonly=True,
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


"""Tables related to Permission Sync"""


class PermissionSyncStatus(str, PyEnum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


class PermissionSyncJobType(str, PyEnum):
    USER_LEVEL = "user_level"
    GROUP_LEVEL = "group_level"


class PermissionSyncRun(Base):
    """Represents one run of a permission sync job. For some given cc_pair, it is either sync-ing
    the users or it is sync-ing the groups"""

    __tablename__ = "permission_sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Not strictly needed but makes it easy to use without fetching from cc_pair
    source_type: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )
    # Currently all sync jobs are handled as a group permission sync or a user permission sync
    update_type: Mapped[PermissionSyncJobType] = mapped_column(
        Enum(PermissionSyncJobType)
    )
    cc_pair_id: Mapped[int | None] = mapped_column(
        ForeignKey("connector_credential_pair.id"), nullable=True
    )
    status: Mapped[PermissionSyncStatus] = mapped_column(Enum(PermissionSyncStatus))
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cc_pair: Mapped[ConnectorCredentialPair] = relationship("ConnectorCredentialPair")


class ExternalPermission(Base):
    """Maps user info both internal and external to the name of the external group
    This maps the user to all of their external groups so that the external group name can be
    attached to the ACL list matching during query time. User level permissions can be handled by
    directly adding the Danswer user to the doc ACL list"""

    __tablename__ = "external_permission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    # Email is needed because we want to keep track of users not in Danswer to simplify process
    # when the user joins
    user_email: Mapped[str] = mapped_column(String)
    source_type: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )
    external_permission_group: Mapped[str] = mapped_column(String)
    user = relationship("User")


class EmailToExternalUserCache(Base):
    """A way to map users IDs in the external tool to a user in Danswer or at least an email for
    when the user joins. Used as a cache for when fetching external groups which have their own
    user ids, this can easily be mapped back to users already known in Danswer without needing
    to call external APIs to get the user emails.

    This way when groups are updated in the external tool and we need to update the mapping of
    internal users to the groups, we can sync the internal users to the external groups they are
    part of using this.

    Ie. User Chris is part of groups alpha, beta, and we can update this if Chris is no longer
    part of alpha in some external tool.
    """

    __tablename__ = "email_to_external_user_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_user_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    # Email is needed because we want to keep track of users not in Danswer to simplify process
    # when the user joins
    user_email: Mapped[str] = mapped_column(String)
    source_type: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, native_enum=False)
    )

    user = relationship("User")


class UsageReport(Base):
    """This stores metadata about usage reports generated by admin including user who generated
    them as well las the period they cover. The actual zip file of the report is stored as a lo
    using the PGFileStore
    """

    __tablename__ = "usage_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_name: Mapped[str] = mapped_column(ForeignKey("file_store.file_name"))

    # if None, report was auto-generated
    requestor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    time_created: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    period_from: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    period_to: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    requestor = relationship("User")
    file = relationship("PGFileStore")
