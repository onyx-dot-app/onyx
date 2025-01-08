from datetime import datetime
from typing import Any
from typing import Generic
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import MASK_CREDENTIAL_PREFIX
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import DocumentErrorSummary
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document as DbDocument
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError as DbIndexAttemptError
from onyx.db.models import IndexingStatus
from onyx.db.models import TaskStatus
from onyx.server.models import FullUserSnapshot
from onyx.server.models import InvitedUserSnapshot
from onyx.server.utils import mask_credential_dict


class DocumentSyncStatus(BaseModel):
    doc_id: str
    last_synced: datetime | None
    last_modified: datetime | None

    @classmethod
    def from_model(cls, doc: DbDocument) -> "DocumentSyncStatus":
        return DocumentSyncStatus(
            doc_id=doc.id,
            last_synced=doc.last_synced,
            last_modified=doc.last_modified,
        )


class DocumentInfo(BaseModel):
    num_chunks: int
    num_tokens: int


class ChunkInfo(BaseModel):
    content: str
    num_tokens: int


class DeletionAttemptSnapshot(BaseModel):
    connector_id: int
    credential_id: int
    status: TaskStatus


class ConnectorBase(BaseModel):
    name: str
    source: DocumentSource
    input_type: InputType
    connector_specific_config: dict[str, Any]
    # In seconds, None for one time index with no refresh
    refresh_freq: int | None = None
    prune_freq: int | None = None
    indexing_start: datetime | None = None


class ConnectorUpdateRequest(ConnectorBase):
    access_type: AccessType
    groups: list[int] = Field(default_factory=list)

    def to_connector_base(self) -> ConnectorBase:
        return ConnectorBase(**self.model_dump(exclude={"access_type", "groups"}))


class ConnectorSnapshot(ConnectorBase):
    id: int
    credential_ids: list[int]
    time_created: datetime
    time_updated: datetime
    source: DocumentSource

    @classmethod
    def from_connector_db_model(cls, connector: Connector) -> "ConnectorSnapshot":
        return ConnectorSnapshot(
            id=connector.id,
            name=connector.name,
            source=connector.source,
            input_type=connector.input_type,
            connector_specific_config=connector.connector_specific_config,
            refresh_freq=connector.refresh_freq,
            prune_freq=connector.prune_freq,
            credential_ids=[
                association.credential.id for association in connector.credentials
            ],
            indexing_start=connector.indexing_start,
            time_created=connector.time_created,
            time_updated=connector.time_updated,
        )


class CredentialSwapRequest(BaseModel):
    new_credential_id: int
    connector_id: int


class CredentialDataUpdateRequest(BaseModel):
    name: str
    credential_json: dict[str, Any]


class CredentialBase(BaseModel):
    credential_json: dict[str, Any]
    # if `true`, then all Admins will have access to the credential
    admin_public: bool
    source: DocumentSource
    name: str | None = None
    curator_public: bool = False
    groups: list[int] = Field(default_factory=list)


class CredentialSnapshot(CredentialBase):
    id: int
    user_id: UUID | None
    time_created: datetime
    time_updated: datetime

    @classmethod
    def from_credential_db_model(cls, credential: Credential) -> "CredentialSnapshot":
        return CredentialSnapshot(
            id=credential.id,
            credential_json=(
                mask_credential_dict(credential.credential_json)
                if MASK_CREDENTIAL_PREFIX and credential.credential_json
                else credential.credential_json
            ),
            user_id=credential.user_id,
            admin_public=credential.admin_public,
            time_created=credential.time_created,
            time_updated=credential.time_updated,
            source=credential.source or DocumentSource.NOT_APPLICABLE,
            name=credential.name,
            curator_public=credential.curator_public,
        )


class IndexAttemptSnapshot(BaseModel):
    id: int
    status: IndexingStatus | None
    new_docs_indexed: int  # only includes completely new docs
    total_docs_indexed: int  # includes docs that are updated
    docs_removed_from_index: int
    error_msg: str | None
    error_count: int
    full_exception_trace: str | None
    time_started: str | None
    time_updated: str

    @classmethod
    def from_index_attempt_db_model(
        cls, index_attempt: IndexAttempt
    ) -> "IndexAttemptSnapshot":
        return IndexAttemptSnapshot(
            id=index_attempt.id,
            status=index_attempt.status,
            new_docs_indexed=index_attempt.new_docs_indexed or 0,
            total_docs_indexed=index_attempt.total_docs_indexed or 0,
            docs_removed_from_index=index_attempt.docs_removed_from_index or 0,
            error_msg=index_attempt.error_msg,
            error_count=len(index_attempt.error_rows),
            full_exception_trace=index_attempt.full_exception_trace,
            time_started=(
                index_attempt.time_started.isoformat()
                if index_attempt.time_started
                else None
            ),
            time_updated=index_attempt.time_updated.isoformat(),
        )


class IndexAttemptError(BaseModel):
    id: int
    index_attempt_id: int | None
    batch_number: int | None
    doc_summaries: list[DocumentErrorSummary]
    error_msg: str | None
    traceback: str | None
    time_created: str

    @classmethod
    def from_db_model(cls, error: DbIndexAttemptError) -> "IndexAttemptError":
        doc_summaries = [
            DocumentErrorSummary.from_dict(summary) for summary in error.doc_summaries
        ]
        return IndexAttemptError(
            id=error.id,
            index_attempt_id=error.index_attempt_id,
            batch_number=error.batch,
            doc_summaries=doc_summaries,
            error_msg=error.error_msg,
            traceback=error.traceback,
            time_created=error.time_created.isoformat(),
        )


# These are the types currently supported by the pagination hook
# More api endpoints can be refactored and be added here for use with the pagination hook
PaginatedType = TypeVar(
    "PaginatedType",
    IndexAttemptSnapshot,
    FullUserSnapshot,
    InvitedUserSnapshot,
)


class PaginatedReturn(BaseModel, Generic[PaginatedType]):
    items: list[PaginatedType]
    total_items: int


class CCPairFullInfo(BaseModel):
    id: int
    name: str
    status: ConnectorCredentialPairStatus
    num_docs_indexed: int
    connector: ConnectorSnapshot
    credential: CredentialSnapshot
    number_of_index_attempts: int
    last_index_attempt_status: IndexingStatus | None
    latest_deletion_attempt: DeletionAttemptSnapshot | None
    access_type: AccessType
    is_editable_for_current_user: bool
    deletion_failure_message: str | None
    indexing: bool
    creator: UUID | None
    creator_email: str | None

    @classmethod
    def from_models(
        cls,
        cc_pair_model: ConnectorCredentialPair,
        latest_deletion_attempt: DeletionAttemptSnapshot | None,
        number_of_index_attempts: int,
        last_index_attempt: IndexAttempt | None,
        num_docs_indexed: int,  # not ideal, but this must be computed separately
        is_editable_for_current_user: bool,
        indexing: bool,
    ) -> "CCPairFullInfo":
        # figure out if we need to artificially deflate the number of docs indexed.
        # This is required since the total number of docs indexed by a CC Pair is
        # updated before the new docs for an indexing attempt. If we don't do this,
        # there is a mismatch between these two numbers which may confuse users.
        last_indexing_status = last_index_attempt.status if last_index_attempt else None
        if (
            last_indexing_status == IndexingStatus.SUCCESS
            and number_of_index_attempts == 1
            and last_index_attempt
            and last_index_attempt.new_docs_indexed
        ):
            num_docs_indexed = (
                last_index_attempt.new_docs_indexed if last_index_attempt else 0
            )

        return cls(
            id=cc_pair_model.id,
            name=cc_pair_model.name,
            status=cc_pair_model.status,
            num_docs_indexed=num_docs_indexed,
            connector=ConnectorSnapshot.from_connector_db_model(
                cc_pair_model.connector
            ),
            credential=CredentialSnapshot.from_credential_db_model(
                cc_pair_model.credential
            ),
            number_of_index_attempts=number_of_index_attempts,
            last_index_attempt_status=last_indexing_status,
            latest_deletion_attempt=latest_deletion_attempt,
            access_type=cc_pair_model.access_type,
            is_editable_for_current_user=is_editable_for_current_user,
            deletion_failure_message=cc_pair_model.deletion_failure_message,
            indexing=indexing,
            creator=cc_pair_model.creator_id,
            creator_email=cc_pair_model.creator.email
            if cc_pair_model.creator
            else None,
        )


class CeleryTaskStatus(BaseModel):
    id: str
    name: str
    status: TaskStatus
    start_time: datetime | None
    register_time: datetime | None


class FailedConnectorIndexingStatus(BaseModel):
    """Simplified version of ConnectorIndexingStatus for failed indexing attempts"""

    cc_pair_id: int
    name: str | None
    error_msg: str | None
    is_deletable: bool
    connector_id: int
    credential_id: int


class ConnectorStatus(BaseModel):
    """
    Represents the status of a connector,
    including indexing status elated information
    """

    cc_pair_id: int
    name: str | None
    connector: ConnectorSnapshot
    credential: CredentialSnapshot
    access_type: AccessType
    groups: list[int]


class ConnectorIndexingStatus(ConnectorStatus):
    """Represents the full indexing status of a connector"""

    cc_pair_status: ConnectorCredentialPairStatus
    owner: str
    last_finished_status: IndexingStatus | None
    last_status: IndexingStatus | None
    last_success: datetime | None
    latest_index_attempt: IndexAttemptSnapshot | None
    docs_indexed: int
    in_progress: bool


class ConnectorCredentialPairIdentifier(BaseModel):
    connector_id: int
    credential_id: int


class ConnectorCredentialPairMetadata(BaseModel):
    name: str | None = None
    access_type: AccessType
    auto_sync_options: dict[str, Any] | None = None
    groups: list[int] = Field(default_factory=list)


class CCStatusUpdateRequest(BaseModel):
    status: ConnectorCredentialPairStatus


class ConnectorCredentialPairDescriptor(BaseModel):
    id: int
    name: str | None = None
    connector: ConnectorSnapshot
    credential: CredentialSnapshot


class RunConnectorRequest(BaseModel):
    connector_id: int
    credential_ids: list[int] | None = None
    from_beginning: bool = False


class CCPropertyUpdateRequest(BaseModel):
    name: str
    value: str


"""Connectors Models"""


class GoogleAppWebCredentials(BaseModel):
    client_id: str
    project_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_secret: str
    redirect_uris: list[str]
    javascript_origins: list[str]


class GoogleAppCredentials(BaseModel):
    web: GoogleAppWebCredentials


class GoogleServiceAccountKey(BaseModel):
    type: str
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_x509_cert_url: str
    universe_domain: str


class GoogleServiceAccountCredentialRequest(BaseModel):
    google_primary_admin: str | None = None  # email of user to impersonate


class FileUploadResponse(BaseModel):
    file_paths: list[str]


class ObjectCreationIdResponse(BaseModel):
    id: int | str
    credential: CredentialSnapshot | None = None


class AuthStatus(BaseModel):
    authenticated: bool


class AuthUrl(BaseModel):
    auth_url: str


class GmailCallback(BaseModel):
    state: str
    code: str


class GDriveCallback(BaseModel):
    state: str
    code: str
