"""Assembles all available text content for a proposal to pass to rule evaluation.

V1 LIMITATION: Document body text (the main text content extracted by connectors)
is stored in Vespa, not in the PostgreSQL Document table. The DB row only stores
metadata (semantic_id, link, tags, primary_owners, etc.). For Jira tickets,
the Description and Comments text are indexed into Vespa during connector runs and
are NOT accessible here without a Vespa query.

As a result, the primary source of rich text for rule evaluation in V1 is:
  - Manually uploaded documents (proposal_review_document.extracted_text)
  - Structured metadata from Tag rows linked to the Document
  - For Jira tickets: the connector stores custom field data in the Tag table
    (tag_key / tag_value pairs), which includes Status, Priority, Assignee, etc.

Future improvement: add a Vespa retrieval step to fetch indexed text chunks for
the parent document and its attachments.
"""

import json
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.models import Document
from onyx.db.models import Tag
from onyx.server.features.proposal_review.db.models import ProposalReviewDocument
from onyx.server.features.proposal_review.db.models import ProposalReviewProposal
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SENTINEL_VALUES = {"Please Select", "please select", "NULL"}

# Metadata keys from the Jira connector that commonly carry useful text content.
# These are extracted from Tag rows and presented as labeled sections to give
# the LLM more signal when evaluating rules.
_JIRA_TEXT_METADATA_KEYS = [
    "description",
    "summary",
    "comment",
    "comments",
    "acceptance_criteria",
    "story_points",
    "priority",
    "status",
    "resolution",
    "issue_type",
    "labels",
    "components",
    "fix_versions",
    "affects_versions",
    "environment",
    "assignee",
    "reporter",
    "creator",
]


@dataclass
class ProposalContext:
    """All text and metadata context assembled for rule evaluation."""

    proposal_text: str  # concatenated text from all documents
    budget_text: str  # best-effort budget section extraction
    foa_text: str  # FOA content (auto-fetched or uploaded)
    metadata: dict[str, Any]  # structured metadata from Document tags
    jira_key: str  # for display/reference
    metadata_raw: dict[str, Any] = field(
        default_factory=dict
    )  # full unresolved metadata


def get_proposal_context(
    proposal_id: UUID,
    db_session: Session,
) -> ProposalContext:
    """Assemble context for rule evaluation.

    Gathers text from three sources:
    1. Jira ticket content (from Document.semantic_id + Tag rows)
    2. Jira attachments (child Documents linked by ID prefix convention)
    3. Manually uploaded documents (from proposal_review_document.extracted_text)

    For MVP, returns full text of everything. Future: smart section selection.
    """
    proposal = (
        db_session.query(ProposalReviewProposal)
        .filter(ProposalReviewProposal.id == proposal_id)
        .one_or_none()
    )
    if not proposal:
        logger.warning("Proposal %s not found during context assembly", proposal_id)
        return ProposalContext(
            proposal_text="",
            budget_text="",
            foa_text="",
            metadata={},
            jira_key="",
            metadata_raw={},
        )

    parent_doc = (
        db_session.query(Document)
        .options(selectinload(Document.tags))
        .filter(Document.id == proposal.document_id)
        .one_or_none()
    )

    jira_key = ""
    metadata: dict[str, Any] = {}
    all_text_parts: list[str] = []
    budget_parts: list[str] = []
    foa_parts: list[str] = []

    if parent_doc:
        jira_key = parent_doc.semantic_id or ""
        metadata = _build_metadata_from_tags(parent_doc.tags)

        # Build text from DB-available fields. The actual ticket body text lives
        # in Vespa and is not accessible here. Tag rows contain structured Jira
        # fields that the connector extracted.
        parent_text = _build_parent_document_text(parent_doc)
        if parent_text:
            all_text_parts.append(parent_text)

        # 3. Look for child Documents (Jira attachments).
        # Jira attachment Documents have IDs of the form:
        #   "{parent_jira_url}/attachments/{attachment_id}"
        # We find them via ID prefix match.
        #
        # V1 LIMITATION: child document text content is in Vespa, not in the
        # DB. We can only extract metadata (filename, mime type, etc.) from
        # the Document row. The actual attachment text is not available here
        # without a Vespa query. See module docstring for details.
        child_docs = _find_child_documents(parent_doc, db_session)
        if child_docs:
            logger.info(
                "Found %d child documents for %s. "
                "Note: their text content is in Vespa and only metadata is "
                "available for rule evaluation.",
                len(child_docs),
                jira_key,
            )
        for child_doc in child_docs:
            child_text = _build_child_document_text(child_doc)
            if child_text:
                all_text_parts.append(child_text)
                _classify_child_text(child_doc, child_text, budget_parts, foa_parts)
    else:
        logger.warning(
            "Parent Document not found for proposal %s "
            "(document_id=%s). "
            "Context will rely on manually uploaded documents only.",
            proposal_id,
            proposal.document_id,
        )

    # 4. Fetch manually uploaded documents from proposal_review_document.
    # This is the PRIMARY source of rich text content for V1 since the
    # extracted_text column holds the full document content.
    manual_docs = (
        db_session.query(ProposalReviewDocument)
        .filter(ProposalReviewDocument.proposal_id == proposal_id)
        .order_by(ProposalReviewDocument.created_at)
        .all()
    )
    for doc in manual_docs:
        if doc.extracted_text:
            all_text_parts.append(
                f"--- Document: {doc.file_name} (role: {doc.document_role}) ---\n"
                f"{doc.extracted_text}"
            )
            # Classify by role
            role_upper = (doc.document_role or "").upper()
            if role_upper == "BUDGET" or _is_budget_filename(doc.file_name):
                budget_parts.append(doc.extracted_text)
            elif role_upper == "FOA":
                foa_parts.append(doc.extracted_text)

    return ProposalContext(
        proposal_text="\n\n".join(all_text_parts) if all_text_parts else "",
        budget_text="\n\n".join(budget_parts) if budget_parts else "",
        foa_text="\n\n".join(foa_parts) if foa_parts else "",
        metadata=metadata,
        jira_key=jira_key,
        metadata_raw=metadata,
    )


def _build_metadata_from_tags(tags: list[Tag]) -> dict[str, Any]:
    """Build a metadata dict from a Document's Tag rows.

    Jira custom field data is stored as Tag rows (tag_key / tag_value),
    NOT in Document.doc_metadata.  This mirrors the approach used in
    proposals_api._resolve_document_metadata.
    """
    metadata: dict[str, Any] = {}
    for tag in tags:
        value = tag.tag_value
        if value in _SENTINEL_VALUES:
            continue
        key = tag.tag_key
        if tag.is_list:
            metadata.setdefault(key, [])
            metadata[key].append(value)
        else:
            metadata[key] = value
    return metadata


def _build_parent_document_text(doc: Document) -> str:
    """Build text representation from a parent Document row (Jira ticket).

    The Document table does NOT store the ticket body text -- that lives in Vespa.
    What we DO have access to:
      - semantic_id: typically "{ISSUE_KEY}: {summary}"
      - link: URL to the Jira ticket
      - tags: Tag rows with structured fields from the connector (status,
        priority, assignee, custom fields, etc.)
      - primary_owners / secondary_owners: people associated with the document

    We extract all available metadata and present it as labeled sections to
    maximize the signal available to the LLM for rule evaluation.
    """
    parts: list[str] = []

    if doc.semantic_id:
        parts.append(f"Document: {doc.semantic_id}")
    if doc.link:
        parts.append(f"Link: {doc.link}")

    if doc.primary_owners:
        parts.append(f"Primary Owners: {', '.join(doc.primary_owners)}")
    if doc.secondary_owners:
        parts.append(f"Secondary Owners: {', '.join(doc.secondary_owners)}")

    metadata = _build_metadata_from_tags(doc.tags)

    # Extract well-known Jira fields as labeled sections
    for key in _JIRA_TEXT_METADATA_KEYS:
        value = metadata.get(key)
        if value is not None and value != "" and value != []:
            label = key.replace("_", " ").title()
            if isinstance(value, list):
                parts.append(f"{label}: {', '.join(str(v) for v in value)}")
            elif isinstance(value, dict):
                parts.append(f"{label}:\n{json.dumps(value, indent=2, default=str)}")
            else:
                parts.append(f"{label}: {value}")

    # Include any remaining metadata keys not in the well-known set
    remaining = {
        k: v
        for k, v in metadata.items()
        if k.lower() not in _JIRA_TEXT_METADATA_KEYS
        and v is not None
        and v != ""
        and v != []
    }
    if remaining:
        parts.append(
            f"Additional Metadata:\n{json.dumps(remaining, indent=2, default=str)}"
        )

    return "\n".join(parts) if parts else ""


def _build_child_document_text(doc: Document) -> str:
    """Build text representation from a child Document row (Jira attachment).

    V1 LIMITATION: The actual extracted text of the attachment lives in Vespa,
    not in the Document table. We can only present metadata from Tag rows
    (filename, mime type, size, parent ticket).

    This means the LLM knows an attachment EXISTS and its metadata, but cannot
    read its contents. Future versions should add a Vespa retrieval step.
    """
    parts: list[str] = []

    if doc.semantic_id:
        parts.append(f"Attachment: {doc.semantic_id}")
    if doc.link:
        parts.append(f"Link: {doc.link}")

    child_metadata = _build_metadata_from_tags(doc.tags)
    for key, value in child_metadata.items():
        if value is not None and value != "":
            label = key.replace("_", " ").title()
            if isinstance(value, list):
                parts.append(f"{label}: {', '.join(str(v) for v in value)}")
            else:
                parts.append(f"{label}: {value}")

    if not parts:
        return ""

    parts.append(
        "[Note: Full attachment text is indexed in Vespa and not available "
        "in this context. Upload the document manually for full text analysis.]"
    )

    return "\n".join(parts)


def _find_child_documents(parent_doc: Document, db_session: Session) -> list[Document]:
    """Find child Documents linked to the parent (e.g. Jira attachments).

    Jira attachments are indexed as separate Document rows whose ID follows
    the convention: "{parent_document_id}/attachments/{attachment_id}".
    The parent_document_id for Jira is the full URL to the issue, e.g.
    "https://jira.example.com/browse/PROJ-123".

    V1 LIMITATION: These child Document rows only contain metadata in the DB.
    Their actual extracted text content is stored in Vespa. To read the
    attachment text, a Vespa query would be required. This is not implemented
    in V1 -- officers should upload key documents manually for full text
    analysis.
    """
    if not parent_doc.id:
        return []

    # Child documents have IDs that start with the parent document's ID
    # followed by a path segment (e.g., /attachments/12345)
    # Escape LIKE wildcards in the document ID
    escaped_id = parent_doc.id.replace("%", r"\%").replace("_", r"\_")
    child_docs = (
        db_session.query(Document)
        .options(selectinload(Document.tags))
        .filter(
            Document.id.like(f"{escaped_id}/%"),
            Document.id != parent_doc.id,
        )
        .all()
    )
    return child_docs


def _classify_child_text(
    doc: Document,
    text: str,
    budget_parts: list[str],
    foa_parts: list[str],
) -> None:
    """Best-effort classification of child document text into budget or FOA."""
    semantic_id = (doc.semantic_id or "").lower()

    if _is_budget_filename(semantic_id):
        budget_parts.append(text)
    elif any(
        term in semantic_id
        for term in ["foa", "funding opportunity", "rfa", "solicitation", "nofo"]
    ):
        foa_parts.append(text)


def _is_budget_filename(filename: str) -> bool:
    """Check if a filename suggests budget content."""
    lower = (filename or "").lower()
    return any(term in lower for term in ["budget", "cost", "financial", "expenditure"])
