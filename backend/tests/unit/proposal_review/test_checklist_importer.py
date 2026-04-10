"""Unit tests for the checklist importer engine component.

Tests cover:
- _parse_import_response: JSON array parsing and validation
- _validate_rule: field validation, type normalization, missing fields
- Compound decomposition (multiple rules sharing a category)
- Refinement detection (refinement_needed / refinement_question)
- Malformed response handling (invalid JSON, non-array)
- import_checklist: empty-input guard and LLM error propagation
"""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.features.proposal_review.engine.checklist_importer import (
    _parse_import_response,
)
from onyx.server.features.proposal_review.engine.checklist_importer import (
    _validate_rule,
)
from onyx.server.features.proposal_review.engine.checklist_importer import (
    import_checklist,
)


# =====================================================================
# _validate_rule  --  single rule validation
# =====================================================================


class TestValidateRule:
    """Tests for _validate_rule (field validation and normalization)."""

    def test_valid_rule_passes(self):
        raw = {
            "name": "Check budget cap",
            "description": "Ensures budget is under $500k",
            "category": "IR-2: Budget",
            "rule_type": "DOCUMENT_CHECK",
            "rule_intent": "CHECK",
            "prompt_template": "Review {{budget_text}} for compliance.",
            "refinement_needed": False,
            "refinement_question": None,
        }
        result = _validate_rule(raw, 0)
        assert result is not None
        assert result["name"] == "Check budget cap"
        assert result["rule_type"] == "DOCUMENT_CHECK"
        assert result["rule_intent"] == "CHECK"
        assert result["refinement_needed"] is False

    def test_missing_name_returns_none(self):
        raw = {"prompt_template": "something"}
        assert _validate_rule(raw, 0) is None

    def test_missing_prompt_template_returns_none(self):
        raw = {"name": "A rule"}
        assert _validate_rule(raw, 0) is None

    def test_invalid_rule_type_defaults_to_custom_nl(self):
        raw = {
            "name": "Test",
            "prompt_template": "t",
            "rule_type": "INVALID_TYPE",
        }
        result = _validate_rule(raw, 0)
        assert result["rule_type"] == "CUSTOM_NL"

    def test_invalid_rule_intent_defaults_to_check(self):
        raw = {
            "name": "Test",
            "prompt_template": "t",
            "rule_intent": "NOTIFY",
        }
        result = _validate_rule(raw, 0)
        assert result["rule_intent"] == "CHECK"

    def test_missing_rule_type_defaults_to_custom_nl(self):
        raw = {"name": "Test", "prompt_template": "t"}
        result = _validate_rule(raw, 0)
        assert result["rule_type"] == "CUSTOM_NL"

    def test_missing_rule_intent_defaults_to_check(self):
        raw = {"name": "Test", "prompt_template": "t"}
        result = _validate_rule(raw, 0)
        assert result["rule_intent"] == "CHECK"

    def test_name_truncated_to_200_chars(self):
        raw = {"name": "x" * 300, "prompt_template": "t"}
        result = _validate_rule(raw, 0)
        assert len(result["name"]) == 200

    def test_refinement_needed_truthy_values(self):
        raw = {
            "name": "Test",
            "prompt_template": "t",
            "refinement_needed": True,
            "refinement_question": "What is the IDC rate?",
        }
        result = _validate_rule(raw, 0)
        assert result["refinement_needed"] is True
        assert result["refinement_question"] == "What is the IDC rate?"

    def test_refinement_needed_defaults_false(self):
        raw = {"name": "Test", "prompt_template": "t"}
        result = _validate_rule(raw, 0)
        assert result["refinement_needed"] is False
        assert result["refinement_question"] is None

    @pytest.mark.parametrize(
        "rule_type",
        ["DOCUMENT_CHECK", "METADATA_CHECK", "CROSS_REFERENCE", "CUSTOM_NL"],
    )
    def test_all_valid_rule_types_accepted(self, rule_type):
        raw = {"name": "Test", "prompt_template": "t", "rule_type": rule_type}
        result = _validate_rule(raw, 0)
        assert result["rule_type"] == rule_type

    @pytest.mark.parametrize("intent", ["CHECK", "HIGHLIGHT"])
    def test_all_valid_intents_accepted(self, intent):
        raw = {"name": "Test", "prompt_template": "t", "rule_intent": intent}
        result = _validate_rule(raw, 0)
        assert result["rule_intent"] == intent


# =====================================================================
# _parse_import_response  --  full array parsing
# =====================================================================


class TestParseImportResponse:
    """Tests for _parse_import_response (JSON array parsing + validation)."""

    def test_parses_valid_array(self):
        rules_json = json.dumps(
            [
                {
                    "name": "Rule A",
                    "description": "Checks A",
                    "category": "Cat-1",
                    "rule_type": "DOCUMENT_CHECK",
                    "rule_intent": "CHECK",
                    "prompt_template": "Check {{proposal_text}}",
                    "refinement_needed": False,
                    "refinement_question": None,
                },
                {
                    "name": "Rule B",
                    "description": "Checks B",
                    "category": "Cat-1",
                    "rule_type": "METADATA_CHECK",
                    "rule_intent": "HIGHLIGHT",
                    "prompt_template": "Check {{metadata.sponsor}}",
                    "refinement_needed": False,
                    "refinement_question": None,
                },
            ]
        )
        result = _parse_import_response(rules_json)
        assert len(result) == 2
        assert result[0]["name"] == "Rule A"
        assert result[1]["name"] == "Rule B"

    def test_strips_markdown_code_fences(self):
        inner = json.dumps([{"name": "R", "prompt_template": "p"}])
        raw = f"```json\n{inner}\n```"
        result = _parse_import_response(raw)
        assert len(result) == 1
        assert result[0]["name"] == "R"

    def test_invalid_json_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            _parse_import_response("not valid json [")

    def test_non_array_json_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="non-array JSON"):
            _parse_import_response('{"name": "single rule"}')

    def test_skips_non_dict_entries(self):
        raw = json.dumps(
            [
                {"name": "Valid", "prompt_template": "p"},
                "this is a string, not a dict",
                42,
            ]
        )
        result = _parse_import_response(raw)
        assert len(result) == 1
        assert result[0]["name"] == "Valid"

    def test_skips_rules_missing_required_fields(self):
        raw = json.dumps(
            [
                {"name": "Valid", "prompt_template": "p"},
                {"description": "no name or template"},
            ]
        )
        result = _parse_import_response(raw)
        assert len(result) == 1

    def test_compound_decomposition_shared_category(self):
        """Multiple rules from the same checklist item share a category."""
        rules_json = json.dumps(
            [
                {
                    "name": "Budget under 500k",
                    "category": "IR-3: Budget Compliance",
                    "prompt_template": "Check if budget < 500k using {{budget_text}}",
                },
                {
                    "name": "Budget justification present",
                    "category": "IR-3: Budget Compliance",
                    "prompt_template": "Check for budget justification in {{proposal_text}}",
                },
                {
                    "name": "Indirect costs correct",
                    "category": "IR-3: Budget Compliance",
                    "prompt_template": "Verify IDC rates in {{budget_text}}",
                    "refinement_needed": True,
                    "refinement_question": "What is the negotiated IDC rate?",
                },
            ]
        )
        result = _parse_import_response(rules_json)
        assert len(result) == 3
        # All share the same category
        categories = {r["category"] for r in result}
        assert categories == {"IR-3: Budget Compliance"}

    def test_refinement_preserved_in_output(self):
        raw = json.dumps(
            [
                {
                    "name": "IDC Rate Check",
                    "prompt_template": "Verify {{INSTITUTION_IDC_RATES}} against {{budget_text}}",
                    "refinement_needed": True,
                    "refinement_question": "What are your institution's IDC rates?",
                }
            ]
        )
        result = _parse_import_response(raw)
        assert len(result) == 1
        assert result[0]["refinement_needed"] is True
        assert "IDC rates" in result[0]["refinement_question"]


# =====================================================================
# import_checklist  --  top-level function
# =====================================================================


class TestImportChecklist:
    """Tests for the top-level import_checklist function."""

    def test_empty_text_returns_empty_list(self):
        assert import_checklist("") == []
        assert import_checklist("   ") == []

    def test_none_text_returns_empty_list(self):
        # The function checks `not extracted_text`, which is True for None
        assert import_checklist(None) == []  # type: ignore[arg-type]

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.get_default_llm"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    def test_successful_import(self, mock_to_string, mock_get_llm):
        rules_json = json.dumps(
            [
                {"name": "Rule 1", "prompt_template": "Check {{proposal_text}}"},
            ]
        )
        mock_to_string.return_value = rules_json
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        result = import_checklist("Some checklist content here.")
        assert len(result) == 1
        assert result[0]["name"] == "Rule 1"
        mock_llm.invoke.assert_called_once()

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.get_default_llm"
    )
    def test_llm_failure_raises_runtime_error(self, mock_get_llm):
        mock_get_llm.side_effect = RuntimeError("No API key")

        with pytest.raises(RuntimeError, match="Failed to parse checklist"):
            import_checklist("Some checklist content.")
