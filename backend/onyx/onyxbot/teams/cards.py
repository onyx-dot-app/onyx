"""Adaptive Card builders for Teams bot responses."""

from onyx.chat.models import ChatFullResponse
from onyx.onyxbot.teams.constants import ADAPTIVE_CARD_SCHEMA
from onyx.onyxbot.teams.constants import ADAPTIVE_CARD_VERSION
from onyx.onyxbot.teams.constants import MAX_CITATIONS


def build_answer_card(
    answer: str,
    response: ChatFullResponse | None = None,
) -> dict:
    """Build an Adaptive Card for a chat answer with optional citations.

    Target Adaptive Card schema version 1.3 for mobile compatibility.
    """
    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": answer,
            "wrap": True,
        }
    ]

    # Add citations if present
    citations = _extract_citations(response) if response else []
    if citations:
        body.append(
            {
                "type": "TextBlock",
                "text": "**Sources:**",
                "wrap": True,
                "spacing": "Medium",
            }
        )
        for num, name, link in citations:
            if link:
                body.append(
                    {
                        "type": "TextBlock",
                        "text": f"{num}. [{name}]({link})",
                        "wrap": True,
                        "spacing": "None",
                    }
                )
            else:
                body.append(
                    {
                        "type": "TextBlock",
                        "text": f"{num}. {name}",
                        "wrap": True,
                        "spacing": "None",
                    }
                )

    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
    }


def build_error_card(message: str) -> dict:
    """Build an Adaptive Card for error messages."""
    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": [
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True,
                "color": "Attention",
            }
        ],
    }


def build_welcome_card() -> dict:
    """Build an Adaptive Card for the welcome message when bot is added."""
    return {
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": ADAPTIVE_CARD_VERSION,
        "body": [
            {
                "type": "TextBlock",
                "text": "Welcome to Onyx!",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "TextBlock",
                "text": (
                    "I'm the Onyx bot. I can help you search your company's knowledge base "
                    "and answer questions.\n\n"
                    "To get started, an admin needs to register this team. "
                    "Send me a direct message with:\n\n"
                    "`@Onyx register <registration_key>`"
                ),
                "wrap": True,
            },
        ],
    }


def _extract_citations(
    response: ChatFullResponse,
) -> list[tuple[int, str, str | None]]:
    """Extract citation information from a chat response."""
    if not response.citation_info or not response.top_documents:
        return []

    cited_docs: list[tuple[int, str, str | None]] = []
    for citation in response.citation_info:
        doc = next(
            (
                d
                for d in response.top_documents
                if d.document_id == citation.document_id
            ),
            None,
        )
        if doc:
            cited_docs.append(
                (
                    citation.citation_number,
                    doc.semantic_identifier or "Source",
                    doc.link,
                )
            )

    cited_docs.sort(key=lambda x: x[0])
    return cited_docs[:MAX_CITATIONS]
