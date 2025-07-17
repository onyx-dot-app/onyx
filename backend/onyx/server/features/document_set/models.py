from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.db.models import DocumentSet as DocumentSetDBModel
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.server.documents.models import CCPairSummary
from onyx.server.documents.models import ConnectorCredentialPairDescriptor
from onyx.server.documents.models import ConnectorSnapshot
from onyx.server.documents.models import CredentialSnapshot
from onyx.server.federated.models import FederatedConnectorSummary


class FederatedConnectorConfig(BaseModel):
    """Configuration for adding a federated connector to a document set"""

    federated_connector_id: int
    entities: dict[str, Any]


class FederatedConnectorDescriptor(BaseModel):
    """Descriptor for a federated connector in a document set"""

    id: int
    name: str
    source: str
    entities: dict[str, Any]

    @classmethod
    def from_federated_connector_mapping(
        cls, fc_mapping: "FederatedConnector__DocumentSet"
    ) -> "FederatedConnectorDescriptor":
        """Create a descriptor from a federated connector mapping"""
        return cls(
            id=fc_mapping.federated_connector_id,
            name=(
                f"{fc_mapping.federated_connector.source.replace('_', ' ').title()}"
                if fc_mapping.federated_connector
                else "Unknown"
            ),
            source=(
                fc_mapping.federated_connector.source
                if fc_mapping.federated_connector
                else "unknown"
            ),
            entities=fc_mapping.entities,
        )


class DocumentSetCreationRequest(BaseModel):
    name: str
    description: str
    cc_pair_ids: list[int]
    is_public: bool
    # For Private Document Sets, who should be able to access these
    users: list[UUID] = Field(default_factory=list)
    groups: list[int] = Field(default_factory=list)
    # Federated connectors to include in the document set
    federated_connectors: list[FederatedConnectorConfig] = Field(default_factory=list)


class DocumentSetUpdateRequest(BaseModel):
    id: int
    description: str
    cc_pair_ids: list[int]
    is_public: bool
    # For Private Document Sets, who should be able to access these
    users: list[UUID]
    groups: list[int]
    # Federated connectors to include in the document set
    federated_connectors: list[FederatedConnectorConfig] = Field(default_factory=list)


class CheckDocSetPublicRequest(BaseModel):
    """Note that this does not mean that the Document Set itself is to be viewable by everyone
    Rather, this refers to the CC-Pairs in the Document Set, and if every CC-Pair is public
    """

    document_set_ids: list[int]


class CheckDocSetPublicResponse(BaseModel):
    is_public: bool


class DocumentSet(BaseModel):
    id: int
    name: str
    description: str | None
    cc_pair_descriptors: list[ConnectorCredentialPairDescriptor]
    is_up_to_date: bool
    is_public: bool
    # For Private Document Sets, who should be able to access these
    users: list[UUID]
    groups: list[int]
    # Federated connectors in the document set
    federated_connectors: list[FederatedConnectorDescriptor] = Field(
        default_factory=list
    )

    @classmethod
    def from_model(cls, document_set_model: DocumentSetDBModel) -> "DocumentSet":
        return cls(
            id=document_set_model.id,
            name=document_set_model.name,
            description=document_set_model.description,
            cc_pair_descriptors=[
                ConnectorCredentialPairDescriptor(
                    id=cc_pair.id,
                    name=cc_pair.name,
                    connector=ConnectorSnapshot.from_connector_db_model(
                        cc_pair.connector
                    ),
                    credential=CredentialSnapshot.from_credential_db_model(
                        cc_pair.credential
                    ),
                    access_type=cc_pair.access_type,
                )
                for cc_pair in document_set_model.connector_credential_pairs
            ],
            is_up_to_date=document_set_model.is_up_to_date,
            is_public=document_set_model.is_public,
            users=[user.id for user in document_set_model.users],
            groups=[group.id for group in document_set_model.groups],
            federated_connectors=[
                FederatedConnectorDescriptor.from_federated_connector_mapping(
                    fc_mapping
                )
                for fc_mapping in document_set_model.federated_connectors
            ],
        )


class DocumentSetSummary(BaseModel):
    """Simplified document set model with minimal data for list views"""

    id: int
    name: str
    description: str | None
    cc_pair_summaries: list[CCPairSummary]
    is_up_to_date: bool
    is_public: bool
    users: list[UUID]
    groups: list[int]
    federated_connector_summaries: list[FederatedConnectorSummary] = Field(
        default_factory=list
    )

    @classmethod
    def from_model(cls, document_set: DocumentSetDBModel) -> "DocumentSetSummary":
        """Create a summary from a DocumentSet database model"""
        return cls(
            id=document_set.id,
            name=document_set.name,
            description=document_set.description,
            cc_pair_summaries=[
                CCPairSummary(
                    id=cc_pair.id,
                    name=cc_pair.name,
                    source=cc_pair.connector.source,
                    access_type=cc_pair.access_type,
                )
                for cc_pair in document_set.connector_credential_pairs
            ],
            is_up_to_date=document_set.is_up_to_date,
            is_public=document_set.is_public,
            users=[user.id for user in document_set.users],
            groups=[group.id for group in document_set.groups],
            federated_connector_summaries=[
                FederatedConnectorSummary(
                    id=fc_mapping.federated_connector_id,
                    name=f"{fc_mapping.federated_connector.source.replace('_', ' ').title()}",
                    source=fc_mapping.federated_connector.source,
                    entities=fc_mapping.entities,
                )
                for fc_mapping in document_set.federated_connectors
                if fc_mapping.federated_connector is not None
            ],
        )
