"""Shared vocabulary for agent-proposed scheduled tasks.

A proposal has no table of its own. The agent's ``propose_scheduled_task``
call already persists its arguments into ``build_message.message_metadata``
(see ``streaming.persist_sandbox_event``), so the transcript row IS the
proposal. Approving one records the decision back onto that same row under
``PROPOSAL_ANNOTATION_KEY``.

Constants only: this module is imported by both the db layer and the API
layer, so it must stay free of either.
"""

from __future__ import annotations

from enum import Enum

# Tool name declared by opencode-plugins/scheduled-task-proposal.ts. Matched
# against ``message_metadata["_meta"]["toolName"]``, never ``title``: the raw
# name only survives in ``_meta`` (``_tool_title`` maps unknown tools to
# "Running tool").
PROPOSAL_TOOL_NAME = "propose_scheduled_task"

# Top-level key holding our decision annotation. Namespaced so it cannot
# collide with the ACP packet fields the rest of the metadata mirrors.
PROPOSAL_ANNOTATION_KEY = "onyxProposal"


class ProposalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProposalOutcome(str, Enum):
    """What a decision request actually did.

    ALREADY_DECIDED is not an error: a card restored from an old transcript
    can be stale, and the caller needs to reconcile rather than to fail.
    """

    CREATED = "CREATED"
    REJECTED = "REJECTED"
    ALREADY_DECIDED = "ALREADY_DECIDED"
