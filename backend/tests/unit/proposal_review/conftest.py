"""Shared fixtures for proposal review engine unit tests."""

import json
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Lightweight stand-in for ProposalContext (avoids importing the real one,
# which pulls in SQLAlchemy models that are irrelevant to pure-logic tests).
# The real dataclass lives in context_assembler.py; we import it directly
# where needed but provide a builder here for convenience.
# ---------------------------------------------------------------------------


@pytest.fixture
def make_proposal_context():
    """Factory fixture that builds a ProposalContext with sensible defaults."""
    from onyx.server.features.proposal_review.engine.context_assembler import (
        ProposalContext,
    )

    def _make(
        proposal_text: str = "Default proposal text.",
        budget_text: str = "",
        foa_text: str = "",
        metadata: dict | None = None,
        jira_key: str = "PROJ-100",
    ) -> "ProposalContext":
        return ProposalContext(
            proposal_text=proposal_text,
            budget_text=budget_text,
            foa_text=foa_text,
            metadata=metadata or {},
            jira_key=jira_key,
        )

    return _make


@pytest.fixture
def make_rule():
    """Factory fixture that builds a minimal mock ProposalReviewRule."""

    def _make(
        name: str = "Test Rule",
        prompt_template: str = "Evaluate: {{proposal_text}}",
        rule_id: UUID | None = None,
    ) -> MagicMock:
        rule = MagicMock()
        rule.id = rule_id or uuid4()
        rule.name = name
        rule.prompt_template = prompt_template
        return rule

    return _make


@pytest.fixture
def well_formed_llm_json() -> str:
    """A valid JSON string matching the expected rule-evaluator response schema."""
    return json.dumps(
        {
            "verdict": "PASS",
            "confidence": "HIGH",
            "evidence": "Section 4.2 states the budget is $500k.",
            "explanation": "The proposal meets the budget cap requirement.",
            "suggested_action": None,
        }
    )
