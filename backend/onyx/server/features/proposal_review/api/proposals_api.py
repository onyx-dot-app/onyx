"""API endpoints for proposals and proposal documents."""

import io
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Connector
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.server.features.proposal_review.api.models import ProposalDocumentResponse
from onyx.server.features.proposal_review.api.models import ProposalListResponse
from onyx.server.features.proposal_review.api.models import ProposalResponse
from onyx.server.features.proposal_review.configs import (
    DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES,
)
from onyx.server.features.proposal_review.db import config as config_db
from onyx.server.features.proposal_review.db import proposals as proposals_db
from onyx.server.features.proposal_review.db.models import ProposalReviewDocument
from onyx.server.features.proposal_review.db.models import ProposalReviewProposal
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()


def _resolve_document_metadata(
    document: Document,
    field_mapping: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve metadata from a Document row using the field_mapping config.

    The field_mapping maps raw Jira metadata keys to display names, e.g.
    {"customfield_10001": "PI Name", "customfield_10002": "Sponsor"}.

    If no field_mapping, returns the raw document metadata.
    """
    # Start with the JSONB doc_metadata column (the actual metadata values)
    raw_metadata: dict[str, Any] = dict(document.doc_metadata or {})

    # Always include title and link from the document row
    raw_metadata["title"] = document.semantic_id
    raw_metadata["link"] = document.link

    if not field_mapping:
        return raw_metadata

    # Build a resolved dict with display names mapped from raw metadata keys
    resolved: dict[str, Any] = {
        "title": raw_metadata.get("title"),
        "link": raw_metadata.get("link"),
    }
    for raw_key, display_name in field_mapping.items():
        resolved[display_name] = raw_metadata.get(raw_key)

    return resolved


@router.get("/proposals", response_model=ProposalListResponse)
def list_proposals(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> ProposalListResponse:
    """List proposals.

    This queries the Document table filtered by the configured Jira project,
    LEFT JOINs proposal_review_proposal for review state, and resolves
    metadata field names via the field_mapping config.

    Creates thin proposal_review_proposal records lazily if they don't exist.
    """
    tenant_id = get_current_tenant_id()

    # Get config for field mapping and Jira project filtering
    config = config_db.get_config(tenant_id, db_session)

    # When no Argus config exists, return an empty list with a hint for the frontend.
    # The frontend can show "Configure a Jira connector in Settings to see proposals."
    if config is None:
        return ProposalListResponse(
            proposals=[],
            total_count=0,
            config_missing=True,
        )

    field_mapping = config.field_mapping if config else None

    # Query documents from the configured Jira connector only,
    # LEFT JOIN proposal state for review tracking.
    # NOTE: Tenant isolation is handled at the schema level (schema-per-tenant).
    # The DB session is already scoped to the current tenant's schema, so
    # cross-tenant data leakage is prevented by the connection itself.
    query = db_session.query(Document, ProposalReviewProposal).outerjoin(
        ProposalReviewProposal,
        Document.id == ProposalReviewProposal.document_id,
    )

    # Filter to only documents from the configured Jira connector
    if config and config.jira_connector_id:
        # Join through DocumentByConnectorCredentialPair to filter by connector
        query = query.join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        ).filter(
            DocumentByConnectorCredentialPair.connector_id == config.jira_connector_id,
        )
    else:
        # No connector configured — filter to Jira source connectors only
        # to avoid showing Slack/GitHub/etc documents
        query = (
            query.join(
                DocumentByConnectorCredentialPair,
                Document.id == DocumentByConnectorCredentialPair.id,
            )
            .join(
                Connector,
                DocumentByConnectorCredentialPair.connector_id == Connector.id,
            )
            .filter(
                Connector.source == DocumentSource.JIRA,
            )
        )

    # Deduplicate rows that can arise from multiple connector-credential pairs
    query = query.distinct(Document.id)

    # If status filter is specified, only show documents with matching proposal status.
    # PENDING is special: documents without a proposal record are implicitly pending.
    if status:
        if status == "PENDING":
            query = query.filter(
                or_(
                    ProposalReviewProposal.status == status,
                    ProposalReviewProposal.id.is_(None),
                ),
            )
        else:
            query = query.filter(ProposalReviewProposal.status == status)

    # Use distinct count to avoid inflation from multi-row JOINs
    # (a Document can appear in multiple ConnectorCredentialPairs).
    total_count = (
        query.with_entities(func.count(func.distinct(Document.id))).scalar() or 0
    )
    results = query.offset(offset).limit(limit).all()

    proposals: list[ProposalResponse] = []
    for document, proposal in results:
        # Lazily create proposal record if it doesn't exist
        if proposal is None:
            proposal = proposals_db.get_or_create_proposal(
                document_id=document.id,
                tenant_id=tenant_id,
                db_session=db_session,
            )

        metadata = _resolve_document_metadata(document, field_mapping)
        proposals.append(ProposalResponse.from_model(proposal, metadata=metadata))

    db_session.commit()
    return ProposalListResponse(proposals=proposals, total_count=total_count)


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
def get_proposal(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> ProposalResponse:
    """Get a single proposal with its metadata from the Document table."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Load the linked Document for metadata
    document = (
        db_session.query(Document)
        .filter(Document.id == proposal.document_id)
        .one_or_none()
    )
    config = config_db.get_config(tenant_id, db_session)
    field_mapping = config.field_mapping if config else None

    metadata: dict[str, Any] = {}
    if document:
        metadata = _resolve_document_metadata(document, field_mapping)

    return ProposalResponse.from_model(proposal, metadata=metadata)


# =============================================================================
# Proposal Documents (manual uploads)
# =============================================================================


@router.post(
    "/proposals/{proposal_id}/documents",
    response_model=ProposalDocumentResponse,
    status_code=201,
)
def upload_document(
    proposal_id: UUID,
    file: UploadFile,
    document_role: str = Form("OTHER"),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ProposalDocumentResponse:
    """Upload a document to a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Read file content
    try:
        file_bytes = file.file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read uploaded file: {str(e)}",
        )

    # Validate file size
    if len(file_bytes) > DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File size {len(file_bytes)} bytes exceeds maximum "
                f"allowed size of {DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES} bytes"
            ),
        )

    # Determine file type from filename
    filename = file.filename or "untitled"
    file_type = None
    if filename:
        parts = filename.rsplit(".", 1)
        if len(parts) > 1:
            file_type = parts[1].upper()

    # Extract text from the uploaded file
    extracted_text = None
    if file_bytes:
        try:
            extracted_text = extract_file_text(
                file=io.BytesIO(file_bytes),
                file_name=filename,
            )
        except Exception as e:
            logger.warning(
                f"Failed to extract text from uploaded file '{filename}': {e}"
            )

    doc = ProposalReviewDocument(
        proposal_id=proposal_id,
        file_name=filename,
        file_type=file_type,
        document_role=document_role,
        uploaded_by=user.id,
        extracted_text=extracted_text,
    )
    db_session.add(doc)
    db_session.commit()
    return ProposalDocumentResponse.from_model(doc)


@router.get(
    "/proposals/{proposal_id}/documents",
    response_model=list[ProposalDocumentResponse],
)
def list_documents(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[ProposalDocumentResponse]:
    """List documents for a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    docs = (
        db_session.query(ProposalReviewDocument)
        .filter(ProposalReviewDocument.proposal_id == proposal_id)
        .order_by(ProposalReviewDocument.created_at)
        .all()
    )
    return [ProposalDocumentResponse.from_model(d) for d in docs]


@router.delete("/proposals/{proposal_id}/documents/{doc_id}", status_code=204)
def delete_document(
    proposal_id: UUID,
    doc_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> None:
    """Delete a manually uploaded document."""
    # Verify the proposal belongs to the current tenant
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    doc = (
        db_session.query(ProposalReviewDocument)
        .filter(
            ProposalReviewDocument.id == doc_id,
            ProposalReviewDocument.proposal_id == proposal_id,
        )
        .one_or_none()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db_session.delete(doc)
    db_session.commit()
