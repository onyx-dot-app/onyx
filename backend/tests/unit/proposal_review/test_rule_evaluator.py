"""Unit tests for the rule evaluator engine component.

Tests cover:
- Template variable substitution (_fill_template)
- LLM response parsing (_parse_llm_response)
- Malformed / missing-field responses
- Markdown code fence stripping
- Verdict and confidence validation/normalization
- Token usage extraction
"""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.features.proposal_review.engine.rule_evaluator import (
    _extract_token_usage,
)
from onyx.server.features.proposal_review.engine.rule_evaluator import _fill_template
from onyx.server.features.proposal_review.engine.rule_evaluator import (
    _parse_llm_response,
)
from onyx.server.features.proposal_review.engine.rule_evaluator import evaluate_rule


# =====================================================================
# _fill_template  --  variable substitution
# =====================================================================


class TestFillTemplate:
    """Tests for _fill_template (prompt variable substitution)."""

    def test_replaces_proposal_text(self, make_proposal_context):
        ctx = make_proposal_context(proposal_text="My great proposal.")
        result = _fill_template("Review: {{proposal_text}}", ctx)
        assert result == "Review: My great proposal."

    def test_replaces_budget_text(self, make_proposal_context):
        ctx = make_proposal_context(budget_text="$100k total")
        result = _fill_template("Budget info: {{budget_text}}", ctx)
        assert result == "Budget info: $100k total"

    def test_replaces_foa_text(self, make_proposal_context):
        ctx = make_proposal_context(foa_text="NSF solicitation 24-567")
        result = _fill_template("FOA: {{foa_text}}", ctx)
        assert result == "FOA: NSF solicitation 24-567"

    def test_replaces_jira_key(self, make_proposal_context):
        ctx = make_proposal_context(jira_key="PROJ-42")
        result = _fill_template("Ticket: {{jira_key}}", ctx)
        assert result == "Ticket: PROJ-42"

    def test_replaces_metadata_as_json(self, make_proposal_context):
        ctx = make_proposal_context(metadata={"sponsor": "NIH", "pi": "Dr. Smith"})
        result = _fill_template("Meta: {{metadata}}", ctx)
        # Should be valid JSON
        parsed = json.loads(result.replace("Meta: ", ""))
        assert parsed["sponsor"] == "NIH"
        assert parsed["pi"] == "Dr. Smith"

    def test_replaces_metadata_dot_field(self, make_proposal_context):
        ctx = make_proposal_context(
            metadata={"sponsor": "NIH", "deadline": "2025-01-15"}
        )
        result = _fill_template(
            "Sponsor is {{metadata.sponsor}}, due {{metadata.deadline}}", ctx
        )
        assert result == "Sponsor is NIH, due 2025-01-15"

    def test_metadata_dot_field_with_dict_value(self, make_proposal_context):
        ctx = make_proposal_context(
            metadata={"budget_detail": {"direct": 100, "indirect": 50}}
        )
        result = _fill_template("Details: {{metadata.budget_detail}}", ctx)
        parsed = json.loads(result.replace("Details: ", ""))
        assert parsed == {"direct": 100, "indirect": 50}

    def test_metadata_dot_field_missing_returns_empty(self, make_proposal_context):
        ctx = make_proposal_context(metadata={"sponsor": "NIH"})
        result = _fill_template("Agency: {{metadata.agency}}", ctx)
        assert result == "Agency: "

    def test_replaces_all_placeholders_in_one_template(self, make_proposal_context):
        ctx = make_proposal_context(
            proposal_text="proposal body",
            budget_text="budget body",
            foa_text="foa body",
            jira_key="PROJ-99",
            metadata={"sponsor": "NSF"},
        )
        template = (
            "{{jira_key}}: {{proposal_text}} | "
            "Budget: {{budget_text}} | FOA: {{foa_text}} | "
            "Sponsor: {{metadata.sponsor}} | All: {{metadata}}"
        )
        result = _fill_template(template, ctx)
        assert "PROJ-99" in result
        assert "proposal body" in result
        assert "budget body" in result
        assert "foa body" in result
        assert "NSF" in result

    def test_none_values_replaced_with_empty_string(self, make_proposal_context):
        ctx = make_proposal_context(
            proposal_text=None,  # type: ignore[arg-type]
            budget_text=None,  # type: ignore[arg-type]
            foa_text=None,  # type: ignore[arg-type]
            jira_key=None,  # type: ignore[arg-type]
        )
        result = _fill_template(
            "{{proposal_text}}|{{budget_text}}|{{foa_text}}|{{jira_key}}", ctx
        )
        assert result == "|||"


# =====================================================================
# _parse_llm_response  --  JSON parsing and validation
# =====================================================================


class TestParseLLMResponse:
    """Tests for _parse_llm_response (JSON parsing / verdict validation)."""

    def test_parses_well_formed_json(self, well_formed_llm_json):
        result = _parse_llm_response(well_formed_llm_json)
        assert result["verdict"] == "PASS"
        assert result["confidence"] == "HIGH"
        assert result["evidence"] == "Section 4.2 states the budget is $500k."
        assert result["explanation"] == "The proposal meets the budget cap requirement."
        assert result["suggested_action"] is None

    def test_strips_markdown_json_fence(self):
        inner = json.dumps(
            {
                "verdict": "FAIL",
                "confidence": "MEDIUM",
                "evidence": "x",
                "explanation": "y",
                "suggested_action": "Fix it.",
            }
        )
        raw = f"```json\n{inner}\n```"
        result = _parse_llm_response(raw)
        assert result["verdict"] == "FAIL"
        assert result["confidence"] == "MEDIUM"
        assert result["suggested_action"] == "Fix it."

    def test_strips_bare_code_fence(self):
        inner = json.dumps(
            {
                "verdict": "FLAG",
                "confidence": "LOW",
                "evidence": "e",
                "explanation": "exp",
                "suggested_action": None,
            }
        )
        raw = f"```\n{inner}\n```"
        result = _parse_llm_response(raw)
        assert result["verdict"] == "FLAG"

    def test_malformed_json_returns_needs_review(self):
        result = _parse_llm_response("this is not json at all")
        assert result["verdict"] == "NEEDS_REVIEW"
        assert result["confidence"] == "LOW"
        assert result["evidence"] is None
        assert "Failed to parse" in result["explanation"]
        assert result["suggested_action"] is not None

    def test_invalid_verdict_normalised_to_needs_review(self):
        raw = json.dumps(
            {
                "verdict": "MAYBE",
                "confidence": "HIGH",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["verdict"] == "NEEDS_REVIEW"

    def test_invalid_confidence_normalised_to_low(self):
        raw = json.dumps(
            {
                "verdict": "PASS",
                "confidence": "VERY_HIGH",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["confidence"] == "LOW"

    def test_missing_verdict_defaults_to_needs_review(self):
        raw = json.dumps(
            {
                "confidence": "HIGH",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["verdict"] == "NEEDS_REVIEW"

    def test_missing_confidence_defaults_to_low(self):
        raw = json.dumps(
            {
                "verdict": "PASS",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["confidence"] == "LOW"

    @pytest.mark.parametrize(
        "verdict", ["PASS", "FAIL", "FLAG", "NEEDS_REVIEW", "NOT_APPLICABLE"]
    )
    def test_all_valid_verdicts_accepted(self, verdict):
        raw = json.dumps(
            {
                "verdict": verdict,
                "confidence": "HIGH",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["verdict"] == verdict

    def test_verdict_case_insensitive(self):
        raw = json.dumps(
            {
                "verdict": "pass",
                "confidence": "high",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result["verdict"] == "PASS"
        assert result["confidence"] == "HIGH"

    def test_whitespace_around_json_is_tolerated(self):
        inner = json.dumps(
            {
                "verdict": "PASS",
                "confidence": "HIGH",
                "evidence": "e",
                "explanation": "x",
                "suggested_action": None,
            }
        )
        raw = f"  \n  {inner}  \n  "
        result = _parse_llm_response(raw)
        assert result["verdict"] == "PASS"


# =====================================================================
# _extract_token_usage
# =====================================================================


class TestExtractTokenUsage:
    """Tests for _extract_token_usage (best-effort token extraction)."""

    def test_extracts_total_tokens(self):
        response = MagicMock()
        response.usage.total_tokens = 1234
        assert _extract_token_usage(response) == 1234

    def test_sums_prompt_and_completion_tokens_when_no_total(self):
        response = MagicMock()
        response.usage.total_tokens = None
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 50
        assert _extract_token_usage(response) == 150

    def test_returns_none_when_no_usage(self):
        response = MagicMock(spec=[])  # no usage attr
        assert _extract_token_usage(response) is None

    def test_returns_none_when_usage_is_none(self):
        response = MagicMock()
        response.usage = None
        assert _extract_token_usage(response) is None


# =====================================================================
# evaluate_rule  --  integration of template + LLM call + parsing
# =====================================================================


class TestEvaluateRule:
    """Tests for the top-level evaluate_rule function with mocked LLM."""

    @patch("onyx.server.features.proposal_review.engine.rule_evaluator.get_default_llm")
    @patch(
        "onyx.server.features.proposal_review.engine.rule_evaluator.llm_response_to_string"
    )
    def test_successful_evaluation(
        self, mock_to_string, mock_get_llm, make_rule, make_proposal_context
    ):
        llm_response_json = json.dumps(
            {
                "verdict": "PASS",
                "confidence": "HIGH",
                "evidence": "Found in section 3.",
                "explanation": "Meets requirement.",
                "suggested_action": None,
            }
        )
        mock_to_string.return_value = llm_response_json

        mock_llm = MagicMock()
        mock_llm.config.model_name = "gpt-4o"
        mock_llm.invoke.return_value = MagicMock(usage=MagicMock(total_tokens=500))
        mock_get_llm.return_value = mock_llm

        rule = make_rule(prompt_template="Check: {{proposal_text}}")
        ctx = make_proposal_context(proposal_text="Grant text here.")

        result = evaluate_rule(rule, ctx)

        assert result["verdict"] == "PASS"
        assert result["confidence"] == "HIGH"
        assert result["llm_model"] == "gpt-4o"
        assert result["llm_tokens_used"] == 500

    @patch("onyx.server.features.proposal_review.engine.rule_evaluator.get_default_llm")
    def test_llm_failure_returns_needs_review(
        self, mock_get_llm, make_rule, make_proposal_context
    ):
        mock_get_llm.side_effect = RuntimeError("API key expired")

        rule = make_rule()
        ctx = make_proposal_context()

        result = evaluate_rule(rule, ctx)

        assert result["verdict"] == "NEEDS_REVIEW"
        assert result["confidence"] == "LOW"
        assert "LLM evaluation failed" in result["explanation"]
        assert result["llm_model"] is None
        assert result["llm_tokens_used"] is None
