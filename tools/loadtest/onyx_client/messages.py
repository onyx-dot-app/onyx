"""The question corpus that search scenarios draw from.

Kept apart from chat_user so it imports without locust.
"""

from __future__ import annotations

import os

# Retrieval is only exercised when queries vary. A short list makes every
# search after warmup an index cache hit (~0.05 s instead of ~0.5-1.5 s per
# novel kNN query), which removes retrieval from the measurement.
#
# Topic accuracy does not matter: kNN returns its k nearest chunks whatever you
# ask, and section selection caps at 10, so the expensive per-section fan-out
# is the same for on-topic and off-topic questions. What matters is spread in
# the embedding space and real words for the keyword half of hybrid search.
# So vary the form (keyword fragments, full questions, long multi-clause asks),
# the length, and the subject area. Most deployments index business documents,
# not engineering docs, so keep the mix broad rather than product-specific.
#
# Override with ONYX_MESSAGES_FILE to test against a known corpus.
DEFAULT_MESSAGES = [
    # Short keyword-style fragments.
    "Q3 revenue forecast",
    "parental leave policy",
    "vendor security review checklist",
    "expense reimbursement limits",
    "data retention schedule",
    "office closure dates",
    "brand guidelines logo usage",
    "customer churn analysis 2025",
    "supplier contract renewal terms",
    "incident postmortem template",
    # Plain questions, business topics.
    "What is our policy on remote work?",
    "How do I submit a purchase order?",
    "Who approves marketing spend over $10,000?",
    "What are the payment terms for enterprise contracts?",
    "How is employee performance reviewed?",
    "What is the process for requesting new hardware?",
    "Which insurance plans are available to staff?",
    "How do we handle a customer data deletion request?",
    "What is the escalation path for a production outage?",
    "When does the fiscal year end?",
    # Plain questions, technical topics.
    "How do I rotate database credentials?",
    "What is the backup and restore procedure?",
    "How is multi-tenancy isolated between customers?",
    "What are the rate limits on the public API?",
    "How do I configure single sign-on with Okta?",
    "What happens when a connector fails mid-sync?",
    "How are embeddings generated and stored?",
    "What network ports need to be open?",
    "How do I debug a failing OAuth connection?",
    "What causes indexing to fall behind?",
    # Longer, multi-clause asks.
    "We are preparing for a SOC 2 audit next quarter. Which controls do we "
    "already have evidence for, and which ones still need owners?",
    "A customer reports that search results went stale after their migration. "
    "What should I check first, and what logs confirm the root cause?",
    "Summarize the decisions from the pricing discussions over the last two "
    "quarters, including what we rejected and why.",
    "I need to brief a new engineer on how documents flow from a connector to "
    "a search result. Walk through each stage and where it can fail.",
    "Compare the tradeoffs between self-hosting and the cloud offering for a "
    "regulated customer with data residency requirements in Germany.",
    "What changed in our onboarding process after the feedback from the "
    "January cohort, and who owns the remaining action items?",
    # Questions carrying names, dates and numbers.
    "What did we agree with Acme Corp in the September 2025 renewal?",
    "Show me the meeting notes from the April 12 planning session.",
    "Which accounts renewed above $50,000 last year?",
    "What did the Q2 2025 board deck say about hiring plans?",
    "Who was the account owner for Northwind before the territory change?",
    # Follow-up style phrasing.
    "Can you explain that in more detail?",
    "What are the exceptions to this rule?",
    "Is there a more recent version of this document?",
    "Why was this approach chosen over the alternative?",
    "Who should I contact about this?",
]


def load_messages() -> list[str]:
    """The question corpus, or the contents of ONYX_MESSAGES_FILE."""
    path = os.environ.get("ONYX_MESSAGES_FILE")
    if not path:
        return DEFAULT_MESSAGES
    with open(path, encoding="utf-8") as handle:
        messages = [line.strip() for line in handle if line.strip()]
    if not messages:
        raise RuntimeError(f"ONYX_MESSAGES_FILE {path} has no questions")
    return messages


_PAD = "Please consider the full context of the conversation so far in detail. "


def sized_message(question: str, target_chars: int) -> str:
    """Pad a question with filler up to ~target_chars so histories grow fast
    enough to cross the summarization threshold (compression testing).

    The newline keeps the question on its own line. The mock reads the first
    line as the search query, so padding never reaches the index."""
    if target_chars <= len(question):
        return question
    filler = _PAD * (target_chars // len(_PAD) + 1)
    return (question + "\n" + filler)[:target_chars]
