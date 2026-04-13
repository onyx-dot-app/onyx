"""Unit tests for the checklist importer engine component.

Tests cover:
- _parse_json_array: JSON array parsing, code-fence stripping, error handling
- _validate_rule: field validation, type normalization, missing fields
- enumerate_checklist_items: LLM response parsing into ChecklistItems
- decompose_checklist_item: LLM response parsing into rule dicts
- Refinement detection (refinement_needed / refinement_question)
"""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.features.proposal_review.engine.checklist_importer import (
    _parse_json_array,
)
from onyx.server.features.proposal_review.engine.checklist_importer import (
    _validate_rule,
)
from onyx.server.features.proposal_review.engine.checklist_importer import ChecklistItem
from onyx.server.features.proposal_review.engine.checklist_importer import (
    decompose_checklist_item,
)
from onyx.server.features.proposal_review.engine.checklist_importer import (
    enumerate_checklist_items,
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
# _parse_json_array  --  JSON array parsing
# =====================================================================


class TestParseJsonArray:
    """Tests for _parse_json_array (JSON parsing + code-fence stripping)."""

    def test_parses_valid_array(self):
        raw = json.dumps([{"name": "Rule A"}, {"name": "Rule B"}])
        result = _parse_json_array(raw, context="test")
        assert len(result) == 2
        assert result[0]["name"] == "Rule A"

    def test_strips_markdown_code_fences(self):
        inner = json.dumps([{"name": "R"}])
        raw = f"```json\n{inner}\n```"
        result = _parse_json_array(raw, context="test")
        assert len(result) == 1
        assert result[0]["name"] == "R"

    def test_strips_plain_code_fences(self):
        inner = json.dumps([{"key": "val"}])
        raw = f"```\n{inner}\n```"
        result = _parse_json_array(raw, context="test")
        assert len(result) == 1

    def test_invalid_json_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            _parse_json_array("not valid json [", context="test")

    def test_non_array_json_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="non-array JSON"):
            _parse_json_array('{"name": "single object"}', context="test")

    def test_empty_array(self):
        result = _parse_json_array("[]", context="test")
        assert result == []

    def test_whitespace_stripped(self):
        raw = "  \n" + json.dumps([{"a": 1}]) + "\n  "
        result = _parse_json_array(raw, context="test")
        assert len(result) == 1


# =====================================================================
# enumerate_checklist_items  --  pass 1
# =====================================================================


class TestEnumerateChecklistItems:
    """Tests for enumerate_checklist_items (LLM → ChecklistItems)."""

    def _make_mock_llm(self) -> MagicMock:
        mock_llm = MagicMock()
        mock_llm.config.model_name = "test-model"
        mock_llm.config.model_provider = "test-provider"
        mock_response = MagicMock()
        mock_llm.invoke.return_value = mock_response
        return mock_llm

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.record_llm_response"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_parses_items(self, mock_span, _mock_record, mock_to_string):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        items_json = json.dumps(
            [
                {
                    "id": "IR-1",
                    "name": "PI Eligibility",
                    "category": "IR-1: PI Eligibility",
                    "description": "Check PI eligibility",
                    "sub_checks": ["PI has PhD", "PI is faculty"],
                },
                {
                    "id": "IR-2",
                    "name": "Budget Review",
                    "category": "IR-2: Budget Review",
                    "description": "Check budget compliance",
                    "sub_checks": ["Under $500k"],
                },
            ]
        )
        mock_to_string.return_value = items_json
        mock_llm = self._make_mock_llm()

        result = enumerate_checklist_items("Some checklist text", mock_llm)

        assert len(result) == 2
        assert result[0].id == "IR-1"
        assert result[0].name == "PI Eligibility"
        assert result[0].sub_checks == ["PI has PhD", "PI is faculty"]
        assert result[1].id == "IR-2"
        mock_llm.invoke.assert_called_once()

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.record_llm_response"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_skips_items_without_name(self, mock_span, _mock_record, mock_to_string):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        items_json = json.dumps(
            [
                {"id": "IR-1", "name": "Valid", "description": "ok"},
                {"id": "IR-2", "description": "missing name"},
            ]
        )
        mock_to_string.return_value = items_json
        mock_llm = self._make_mock_llm()

        result = enumerate_checklist_items("text", mock_llm)
        assert len(result) == 1
        assert result[0].name == "Valid"

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.record_llm_response"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_generates_default_id(self, mock_span, _mock_record, mock_to_string):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        items_json = json.dumps([{"name": "No ID Item"}])
        mock_to_string.return_value = items_json
        mock_llm = self._make_mock_llm()

        result = enumerate_checklist_items("text", mock_llm)
        assert len(result) == 1
        assert result[0].id == "ITEM-1"

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_llm_failure_raises_runtime_error(self, mock_span):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        mock_llm = MagicMock()
        mock_llm.config.model_name = "test-model"
        mock_llm.config.model_provider = "test-provider"
        mock_llm.invoke.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="Failed to enumerate"):
            enumerate_checklist_items("text", mock_llm)


# =====================================================================
# decompose_checklist_item  --  pass 2
# =====================================================================


class TestDecomposeChecklistItem:
    """Tests for decompose_checklist_item (ChecklistItem → rule dicts)."""

    SAMPLE_ITEM = ChecklistItem(
        id="IR-3",
        name="Budget Compliance",
        category="IR-3: Budget Compliance",
        description="Check budget compliance",
        sub_checks=["Budget under 500k", "IDC rates correct"],
    )

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.record_llm_response"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_decomposes_into_rules(self, mock_span, _mock_record, mock_to_string):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        rules_json = json.dumps(
            [
                {
                    "name": "Budget under 500k",
                    "description": "Check budget cap",
                    "category": "IR-3: Budget Compliance",
                    "rule_type": "DOCUMENT_CHECK",
                    "rule_intent": "CHECK",
                    "prompt_template": "Check {{budget_text}} for cap.",
                },
                {
                    "name": "IDC rates correct",
                    "description": "Verify IDC rates",
                    "category": "IR-3: Budget Compliance",
                    "rule_type": "DOCUMENT_CHECK",
                    "rule_intent": "CHECK",
                    "prompt_template": "Check {{budget_text}} for IDC.",
                    "refinement_needed": True,
                    "refinement_question": "What is the IDC rate?",
                },
            ]
        )
        mock_to_string.return_value = rules_json
        mock_llm = MagicMock()
        mock_llm.config.model_name = "test-model"
        mock_llm.config.model_provider = "test-provider"

        result = decompose_checklist_item(self.SAMPLE_ITEM, "checklist text", mock_llm)

        assert len(result) == 2
        assert result[0]["name"] == "Budget under 500k"
        assert result[1]["refinement_needed"] is True
        assert result[1]["refinement_question"] == "What is the IDC rate?"

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_response_to_string"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.record_llm_response"
    )
    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_fills_missing_category_from_item(
        self, mock_span, _mock_record, mock_to_string
    ):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        rules_json = json.dumps(
            [
                {
                    "name": "Some rule",
                    "prompt_template": "Check {{proposal_text}}",
                    # no category — should inherit from item
                },
            ]
        )
        mock_to_string.return_value = rules_json
        mock_llm = MagicMock()
        mock_llm.config.model_name = "test-model"
        mock_llm.config.model_provider = "test-provider"

        result = decompose_checklist_item(self.SAMPLE_ITEM, "text", mock_llm)

        assert len(result) == 1
        assert result[0]["category"] == "IR-3: Budget Compliance"

    @patch(
        "onyx.server.features.proposal_review.engine.checklist_importer.llm_generation_span"
    )
    def test_llm_failure_raises_runtime_error(self, mock_span):
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)

        mock_llm = MagicMock()
        mock_llm.config.model_name = "test-model"
        mock_llm.config.model_provider = "test-provider"
        mock_llm.invoke.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="LLM call failed"):
            decompose_checklist_item(self.SAMPLE_ITEM, "text", mock_llm)
