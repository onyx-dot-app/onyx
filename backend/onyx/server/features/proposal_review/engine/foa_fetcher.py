"""Auto-fetches Funding Opportunity Announcements using Onyx web search infrastructure."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewDocument
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Map known opportunity ID prefixes to federal agency domains
_AGENCY_DOMAINS: dict[str, str] = {
    "RFA": "grants.nih.gov",
    "PA": "grants.nih.gov",
    "PAR": "grants.nih.gov",
    "R01": "grants.nih.gov",
    "R21": "grants.nih.gov",
    "U01": "grants.nih.gov",
    "NOT": "grants.nih.gov",
    "NSF": "nsf.gov",
    "DE-FOA": "energy.gov",
    "HRSA": "hrsa.gov",
    "W911": "grants.gov",  # DoD
    "FA": "grants.gov",  # Air Force
    "N00": "grants.gov",  # Navy
    "NOFO": "grants.gov",
}


def fetch_foa(
    opportunity_id: str,
    proposal_id: UUID,
    db_session: Session,
) -> str | None:
    """Fetch FOA content given an opportunity ID.

    1. Determine domain from ID prefix (RFA/PA -> nih.gov, NSF -> nsf.gov, etc.)
    2. Build search query
    3. Call Onyx web search provider
    4. Fetch full content from best URL
    5. Save as proposal_review_document with role=FOA
    6. Return extracted text or None

    If the web search provider is not configured, logs a warning and returns None.
    """
    if not opportunity_id or not opportunity_id.strip():
        logger.debug("No opportunity_id provided, skipping FOA fetch")
        return None

    opportunity_id = opportunity_id.strip()

    # Check if we already have an FOA document for this proposal
    existing_foa = (
        db_session.query(ProposalReviewDocument)
        .filter(
            ProposalReviewDocument.proposal_id == proposal_id,
            ProposalReviewDocument.document_role == "FOA",
        )
        .first()
    )
    if existing_foa and existing_foa.extracted_text:
        logger.info(
            f"FOA document already exists for proposal {proposal_id}, skipping fetch"
        )
        return existing_foa.extracted_text

    # Determine search domain from opportunity ID prefix
    site_domain = _determine_domain(opportunity_id)

    # Build search query
    search_query = f"{opportunity_id} funding opportunity announcement"
    if site_domain:
        search_query = f"site:{site_domain} {opportunity_id}"

    # Try to get the web search provider
    try:
        from onyx.tools.tool_implementations.web_search.providers import (
            get_default_provider,
        )

        provider = get_default_provider()
    except Exception as e:
        logger.warning(f"Failed to load web search provider: {e}")
        provider = None

    if provider is None:
        logger.warning(
            "No web search provider configured. Cannot auto-fetch FOA. "
            "Configure a web search provider in Admin settings to enable this feature."
        )
        return None

    # Search for the FOA
    try:
        results = provider.search(search_query)
    except Exception as e:
        logger.error(f"Web search failed for FOA '{opportunity_id}': {e}")
        return None

    if not results:
        logger.info(f"No search results found for FOA '{opportunity_id}'")
        return None

    # Pick the best result URL
    best_url = str(results[0].link)
    logger.info(f"Fetching FOA content from: {best_url}")

    # Fetch full content from the URL
    try:
        from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
            OnyxWebCrawler,
        )

        crawler = OnyxWebCrawler()
        contents = crawler.contents([best_url])

        if (
            not contents
            or not contents[0].scrape_successful
            or not contents[0].full_content
        ):
            logger.warning(f"No content extracted from FOA URL: {best_url}")
            return None

        foa_text = contents[0].full_content

    except Exception as e:
        logger.error(f"Failed to fetch FOA content from {best_url}: {e}")
        return None

    # Save as a proposal_review_document with role=FOA
    try:
        foa_doc = ProposalReviewDocument(
            proposal_id=proposal_id,
            file_name=f"FOA_{opportunity_id}.html",
            file_type="HTML",
            document_role="FOA",
            extracted_text=foa_text,
            # uploaded_by is None for auto-fetched documents
        )
        db_session.add(foa_doc)
        db_session.flush()
        logger.info(
            f"Saved FOA document for proposal {proposal_id} "
            f"(opportunity_id={opportunity_id}, {len(foa_text)} chars)"
        )
    except Exception as e:
        logger.error(f"Failed to save FOA document: {e}")
        # Still return the text even if save fails
        return foa_text

    return foa_text


def _determine_domain(opportunity_id: str) -> str | None:
    """Determine the likely agency domain from the opportunity ID prefix."""
    upper_id = opportunity_id.upper()

    for prefix, domain in _AGENCY_DOMAINS.items():
        if upper_id.startswith(prefix):
            return domain

    # If it looks like a grants.gov number (numeric), try grants.gov
    if opportunity_id.replace("-", "").isdigit():
        return "grants.gov"

    return None
