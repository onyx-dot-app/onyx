"""Eval-question dataset for the source-scope filter extraction.

Each case is one direct `decide_search_scope` invocation: the user-side
conversation, the connected sources, the cycle state, and the exact scope the
flow must return (`None` == unscoped, search everything). The regression runner
in `test_filter_extraction_regression.py` scores the whole set against a pass
threshold, so a prompt change that flips a behavior shows up as a score drop
rather than a single flaky test.

Cases are distilled from the behaviors the prompt is responsible for (see the
suite README): never inventing a filter from a topic, COMBINED holding its set,
BACKOFF advancing/re-searching/exhausting, and directives carrying (or not
carrying) across turns.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.constants import DocumentSource
from onyx.secondary_llm_flows.source_filter import SearchCycle

ASANA = DocumentSource.ASANA
CONFLUENCE = DocumentSource.CONFLUENCE
GITHUB = DocumentSource.GITHUB
GMAIL = DocumentSource.GMAIL
GOOGLE_DRIVE = DocumentSource.GOOGLE_DRIVE
HIGHSPOT = DocumentSource.HIGHSPOT
JIRA = DocumentSource.JIRA
SALESFORCE = DocumentSource.SALESFORCE
SLACK = DocumentSource.SLACK
ZENDESK = DocumentSource.ZENDESK


class ScopeEvalCase(BaseModel):
    name: str
    # Reporting bucket: "unscoped" | "combined" | "backoff" | "multi-turn".
    category: str
    # User-side turns, oldest first; the last one is the current user query.
    user_turns: list[str]
    connected_sources: list[DocumentSource]
    # This cycle's search queries.
    current_queries: list[str]
    # Earlier cycles of this same user turn (queries + sources searched).
    previous_cycles: list[SearchCycle] = Field(default_factory=list)
    # Exact scope the flow must return; None == unscoped (search everything).
    expected: set[DocumentSource] | None


def _cycle(n: int, queries: list[str], sources: list[str]) -> SearchCycle:
    return SearchCycle(cycle_number=n, queries=queries, searched_sources=sources)


SCOPE_EVAL_CASES: list[ScopeEvalCase] = [
    # --- UNSCOPED: no source named must never invent a filter ---------------
    ScopeEvalCase(
        name="plain-question-no-source",
        category="unscoped",
        user_turns=["What's our standard process for requesting time off?"],
        connected_sources=[CONFLUENCE, SLACK, JIRA],
        current_queries=["time off request process"],
        expected=None,
    ),
    ScopeEvalCase(
        name="topic-is-not-a-source",
        category="unscoped",
        user_turns=["How do we handle on-call rotations?"],
        connected_sources=[CONFLUENCE, SLACK, JIRA],
        current_queries=["on-call rotation handling"],
        expected=None,
    ),
    ScopeEvalCase(
        name="product-name-is-not-a-connected-source",
        category="unscoped",
        user_turns=["How do we configure Datadog alerts for the API servers?"],
        connected_sources=[CONFLUENCE, SLACK, GITHUB],
        current_queries=["Datadog alert configuration API servers"],
        expected=None,
    ),
    ScopeEvalCase(
        name="named-source-not-connected",
        category="unscoped",
        user_turns=["Search SharePoint for the Q3 budget deck."],
        connected_sources=[GOOGLE_DRIVE, SLACK],
        current_queries=["Q3 budget deck"],
        expected=None,
    ),
    ScopeEvalCase(
        name="explicit-search-everything",
        category="unscoped",
        user_turns=["Search all our sources for any mention of Project Falcon."],
        connected_sources=[CONFLUENCE, SLACK, JIRA],
        current_queries=["Project Falcon"],
        expected=None,
    ),
    ScopeEvalCase(
        name="broad-connected-no-directive",
        category="unscoped",
        user_turns=["Summarize what we know about the Q3 roadmap."],
        connected_sources=[CONFLUENCE, SLACK, JIRA, GITHUB, GOOGLE_DRIVE, ZENDESK],
        current_queries=["Q3 roadmap plans"],
        expected=None,
    ),
    # --- FALSE-POSITIVE TRAPS: a CONNECTED source is named, but as the topic
    # --- of the question, not as where to look — must stay unfiltered.
    # --- (currently failing: the prompt scopes to topic-named sources; the
    # --- WHERE-vs-TOPIC tuning that fixes these is landing separately) -------
    ScopeEvalCase(
        # Real reported failure: scoped to gmail/highspot when the connectors
        # are the SUBJECT of the question ("which customers use them").
        name="connector-as-topic-not-directive",
        category="false-positive",
        user_turns=[
            "Which customers use the highspot connector and/or gmail connector?"
        ],
        connected_sources=[GMAIL, HIGHSPOT, SALESFORCE, SLACK, CONFLUENCE],
        current_queries=["customers using highspot connector gmail connector"],
        expected=None,
    ),
    ScopeEvalCase(
        name="integration-setup-question",
        category="false-positive",
        user_turns=["How do I set up the Jira integration for our workspace?"],
        connected_sources=[JIRA, CONFLUENCE, SLACK],
        current_queries=["Jira integration workspace setup"],
        expected=None,
    ),
    ScopeEvalCase(
        name="policy-about-source-tool",
        category="false-positive",
        user_turns=["What's our policy on sending customer emails from Gmail?"],
        connected_sources=[GMAIL, CONFLUENCE, SLACK],
        current_queries=["customer email sending policy Gmail"],
        expected=None,
    ),
    ScopeEvalCase(
        name="tool-ownership-question",
        category="false-positive",
        user_turns=["Who maintains our Slack bot and where does its code live?"],
        connected_sources=[SLACK, GITHUB, CONFLUENCE],
        current_queries=["Slack bot maintainer code repository"],
        expected=None,
    ),
    # --- COMBINED: named set held, every cycle -------------------------------
    ScopeEvalCase(
        name="single-named-source",
        category="combined",
        user_turns=["Find the deployment runbook in Confluence."],
        connected_sources=[CONFLUENCE, GITHUB, SLACK],
        current_queries=["deployment runbook"],
        expected={CONFLUENCE},
    ),
    ScopeEvalCase(
        name="two-sources-combined",
        category="combined",
        user_turns=["Search both Zendesk and Asana for the deploy runbook."],
        connected_sources=[ZENDESK, ASANA, CONFLUENCE],
        current_queries=["deploy runbook"],
        expected={ZENDESK, ASANA},
    ),
    ScopeEvalCase(
        name="three-sources-combined",
        category="combined",
        user_turns=[
            "Check Confluence, Jira, and Slack for anything about the pricing change."
        ],
        connected_sources=[CONFLUENCE, JIRA, SLACK, GITHUB],
        current_queries=["pricing change discussion"],
        expected={CONFLUENCE, JIRA, SLACK},
    ),
    ScopeEvalCase(
        name="combined-holds-across-cycles",
        category="combined",
        user_turns=["Search both Zendesk and Asana for whatever I ask."],
        connected_sources=[ZENDESK, ASANA, CONFLUENCE],
        current_queries=["unrelated payroll question"],
        previous_cycles=[_cycle(1, ["deploy runbook"], ["zendesk", "asana"])],
        expected={ZENDESK, ASANA},
    ),
    ScopeEvalCase(
        name="single-source-repeat-cycle-holds",
        category="combined",
        user_turns=["Search Google Drive for our SLA doc."],
        connected_sources=[GOOGLE_DRIVE, CONFLUENCE, ZENDESK],
        current_queries=["SLA response time commitment"],
        previous_cycles=[_cycle(1, ["SLA uptime guarantee"], ["google_drive"])],
        expected={GOOGLE_DRIVE},
    ),
    ScopeEvalCase(
        name="mixed-valid-and-invalid-sources",
        category="combined",
        user_turns=["Look in Notion and Slack for the launch announcement."],
        connected_sources=[SLACK, CONFLUENCE],
        current_queries=["launch announcement"],
        expected={SLACK},
    ),
    # --- BACKOFF: one source per cycle; advance, re-search, exhaust ----------
    ScopeEvalCase(
        name="backoff-first-cycle-picks-first-source",
        category="backoff",
        user_turns=[
            "Check Zendesk first. If you don't find anything, check Asana. "
            "Help me resolve this support ticket about a billing error."
        ],
        connected_sources=[ZENDESK, ASANA],
        current_queries=["billing error ticket"],
        expected={ZENDESK},
    ),
    ScopeEvalCase(
        name="backoff-advances-when-on-topic",
        category="backoff",
        user_turns=[
            "Check Zendesk first. If you don't find anything, check Asana. "
            "Help me resolve this support ticket about a billing error."
        ],
        connected_sources=[ZENDESK, ASANA],
        current_queries=["customer billing charge dispute"],
        previous_cycles=[_cycle(1, ["billing error support ticket"], ["zendesk"])],
        expected={ASANA},
    ),
    ScopeEvalCase(
        name="backoff-re-searches-on-topic-shift",
        category="backoff",
        user_turns=[
            "For anything I ask, check Zendesk first, then Asana if nothing turns up."
        ],
        connected_sources=[ZENDESK, ASANA],
        current_queries=["expense reimbursement policy limits"],
        previous_cycles=[_cycle(1, ["VPN client setup instructions"], ["zendesk"])],
        expected={ZENDESK},
    ),
    ScopeEvalCase(
        name="backoff-three-sources-advances-to-third",
        category="backoff",
        user_turns=[
            "Check Zendesk first, then Asana, then Google Drive for the "
            "enterprise contract terms."
        ],
        connected_sources=[ZENDESK, ASANA, GOOGLE_DRIVE],
        current_queries=["enterprise customer contract clauses"],
        previous_cycles=[
            _cycle(1, ["enterprise contract terms"], ["zendesk"]),
            _cycle(2, ["enterprise agreement terms"], ["asana"]),
        ],
        expected={GOOGLE_DRIVE},
    ),
    ScopeEvalCase(
        name="backoff-exhausted-scopes-to-all-named",
        category="backoff",
        user_turns=[
            "Check Zendesk first, then Asana, then Google Drive for the "
            "enterprise contract terms."
        ],
        connected_sources=[ZENDESK, ASANA, GOOGLE_DRIVE],
        current_queries=["enterprise contract renewal terms"],
        previous_cycles=[
            _cycle(1, ["enterprise contract terms"], ["zendesk"]),
            _cycle(2, ["enterprise agreement terms"], ["asana"]),
            _cycle(3, ["enterprise customer contract clauses"], ["google_drive"]),
        ],
        expected={ZENDESK, ASANA, GOOGLE_DRIVE},
    ),
    ScopeEvalCase(
        name="backoff-standing-directive-restarts-on-new-turn",
        category="backoff",
        user_turns=[
            "Check Zendesk first, then Asana for anything I ask.",
            "How do I reset a customer's 2FA?",
        ],
        connected_sources=[ZENDESK, ASANA, CONFLUENCE],
        current_queries=["reset customer 2FA"],
        expected={ZENDESK},
    ),
    # --- MULTI-TURN: directives carrying (or not) across turns ---------------
    ScopeEvalCase(
        name="single-source-persists-across-followup",
        category="multi-turn",
        user_turns=[
            "Search Google Drive for our SLA doc.",
            "Can you find more detail on the response time commitment?",
        ],
        connected_sources=[GOOGLE_DRIVE, CONFLUENCE, ZENDESK],
        current_queries=["SLA response time commitment"],
        expected={GOOGLE_DRIVE},
    ),
    ScopeEvalCase(
        name="latest-directive-overrides-earlier",
        category="multi-turn",
        user_turns=[
            "Search Zendesk for the login bug.",
            "Now look in Confluence for the deploy runbook instead.",
        ],
        connected_sources=[ZENDESK, CONFLUENCE, GOOGLE_DRIVE],
        current_queries=["deploy runbook"],
        expected={CONFLUENCE},
    ),
    ScopeEvalCase(
        name="explicit-broaden-overrides-directive",
        category="multi-turn",
        user_turns=[
            "Only use Zendesk for my questions. What's the status of the login bug?",
            "Actually, search across all our sources this time — anything "
            "about the checkout outage.",
        ],
        connected_sources=[ZENDESK, CONFLUENCE, SLACK],
        current_queries=["checkout outage"],
        expected=None,
    ),
    ScopeEvalCase(
        name="standing-directive-applies-to-later-turn",
        category="multi-turn",
        user_turns=[
            "For anything I ask, always check Zendesk only.",
            "What's our refund processing time?",
        ],
        connected_sources=[ZENDESK, CONFLUENCE, SLACK],
        current_queries=["refund processing time"],
        expected={ZENDESK},
    ),
    ScopeEvalCase(
        name="one-off-directive-does-not-leak-to-new-topic",
        category="multi-turn",
        user_turns=[
            "Search Zendesk for the login bug ticket.",
            "What's our parental leave policy?",
        ],
        connected_sources=[ZENDESK, CONFLUENCE, GOOGLE_DRIVE],
        current_queries=["parental leave policy"],
        expected=None,
    ),
]
