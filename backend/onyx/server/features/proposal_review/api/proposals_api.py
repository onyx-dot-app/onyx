"""API endpoints for proposals and proposal documents."""

import io
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Connector
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
    visible_fields: list[str] | None,
) -> dict[str, Any]:
    """Resolve metadata from a Document's tags, filtered to visible fields.

    Jira custom fields are stored as Tag rows (tag_key / tag_value)
    linked to the document via document__tag.  visible_fields selects
    which tag keys to include.  If None/empty, returns all tags.
    """
    # Build metadata from the document's tags
    raw_metadata: dict[str, Any] = {}
    for tag in document.tags:
        key = tag.tag_key
        value = tag.tag_value
        # Tags with is_list=True can have multiple values for the same key
        if tag.is_list:
            raw_metadata.setdefault(key, [])
            raw_metadata[key].append(value)
        else:
            raw_metadata[key] = value

    # Extract jira_key from tags and clean title from semantic_id.
    # Jira semantic_id is "KEY-123: Summary Text" — split to isolate each.
    jira_key = raw_metadata.get("key", "")
    title = document.semantic_id or ""
    if title and ": " in title:
        title = title.split(": ", 1)[1]

    raw_metadata["jira_key"] = jira_key
    raw_metadata["title"] = title
    raw_metadata["link"] = document.link

    if not visible_fields:
        return raw_metadata

    # Filter to only the selected fields, plus always include core fields
    resolved: dict[str, Any] = {
        "jira_key": raw_metadata.get("jira_key"),
        "title": raw_metadata.get("title"),
        "link": raw_metadata.get("link"),
    }
    for key in visible_fields:
        if key in raw_metadata:
            resolved[key] = raw_metadata[key]

    return resolved


@router.get("/proposals")
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

    Documents without a proposal record are returned with status PENDING
    without persisting any new rows (read-only endpoint).
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

    visible_fields = config.field_mapping

    # Query documents from the configured Jira connector only,
    # LEFT JOIN proposal state for review tracking.
    # NOTE: Tenant isolation is handled at the schema level (schema-per-tenant).
    # The DB session is already scoped to the current tenant's schema, so
    # cross-tenant data leakage is prevented by the connection itself.
    query = (
        db_session.query(Document, ProposalReviewProposal)
        .outerjoin(
            ProposalReviewProposal,
            Document.id == ProposalReviewProposal.document_id,
        )
        .options(selectinload(Document.tags))
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

    # Exclude attachment documents — they are children of issue documents
    # and have "/attachments/" in their document ID.
    query = query.filter(~Document.id.contains("/attachments/"))

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

    # Count before adding DISTINCT ON — count(distinct(...)) handles
    # deduplication on its own and conflicts with DISTINCT ON.
    total_count = (
        query.with_entities(func.count(func.distinct(Document.id))).scalar() or 0
    )

    # Deduplicate rows that can arise from multiple connector-credential pairs.
    # Applied after counting to avoid the DISTINCT ON + aggregate conflict.
    # ORDER BY Document.id is required for DISTINCT ON to be deterministic.
    query = query.distinct(Document.id).order_by(Document.id)
    results = query.offset(offset).limit(limit).all()

    proposals: list[ProposalResponse] = []
    for document, proposal in results:
        if proposal is None:
            # Don't create DB records during GET — treat as pending
            metadata = _resolve_document_metadata(document, visible_fields)
            proposals.append(
                ProposalResponse(
                    id=uuid4(),  # temporary, not persisted
                    document_id=document.id,
                    tenant_id=tenant_id,
                    status="PENDING",
                    created_at=document.doc_updated_at or datetime.now(timezone.utc),
                    updated_at=document.doc_updated_at or datetime.now(timezone.utc),
                    metadata=metadata,
                )
            )
            continue
        metadata = _resolve_document_metadata(document, visible_fields)
        proposals.append(ProposalResponse.from_model(proposal, metadata=metadata))

    return ProposalListResponse(proposals=proposals, total_count=total_count)


@router.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> ProposalResponse:
    """Get a single proposal with its metadata from the Document table."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    # Load the linked Document for metadata
    document = (
        db_session.query(Document)
        .options(selectinload(Document.tags))
        .filter(Document.id == proposal.document_id)
        .one_or_none()
    )
    config = config_db.get_config(tenant_id, db_session)
    visible_fields = config.field_mapping if config else None

    metadata: dict[str, Any] = {}
    if document:
        metadata = _resolve_document_metadata(document, visible_fields)

    return ProposalResponse.from_model(proposal, metadata=metadata)


# =============================================================================
# Proposal Documents (manual uploads)
# =============================================================================


@router.post(
    "/proposals/{proposal_id}/documents",
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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    # Read file content
    try:
        file_bytes = file.file.read()
    except Exception as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Failed to read uploaded file: {str(e)}",
        )

    # Validate file size
    if len(file_bytes) > DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"File size {len(file_bytes)} bytes exceeds maximum "
            f"allowed size of {DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES} bytes",
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


@router.get("/proposals/{proposal_id}/documents")
def list_documents(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[ProposalDocumentResponse]:
    """List documents for a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    doc = (
        db_session.query(ProposalReviewDocument)
        .filter(
            ProposalReviewDocument.id == doc_id,
            ProposalReviewDocument.proposal_id == proposal_id,
        )
        .one_or_none()
    )
    if not doc:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Document not found")
    db_session.delete(doc)
    db_session.commit()
