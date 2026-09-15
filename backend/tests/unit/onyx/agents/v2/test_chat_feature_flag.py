import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from onyx.agents.v2.chat_adapter import chat_harness_enabled, request_harness_enabled
from onyx.tools.tool_implementations.search.search_tool import SearchTool


class ChatFeatureFlagTests(unittest.TestCase):
    def setUp(self):
        self.req = NS(
            deep_research=False,
            file_descriptors=[],
            forced_tool_id=None,
            allowed_tool_ids=None,
            additional_context=None,
        )
        self.session = NS(project_id=None, incognito_record_mode=None)
        self.setup = NS(
            new_msg_req=self.req,
            chat_session_project_id=None,
            extracted_context_files=NS(file_metadata=[]),
            search_params=NS(project_id_filter=None, persona_id_filter=None),
            incognito_record_mode=None,
            forced_tool_id=None,
        )
        self.tools = [Mock(spec=SearchTool)]

    def enabled(self):
        return chat_harness_enabled(self.setup, 1, self.tools)

    def test_off_is_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.enabled())
            self.assertFalse(request_harness_enabled(self.req, self.session, 1))

    def test_explicit_on_and_off(self):
        for value, expected in [
            ("true", True),
            ("false", False),
            ("1", False),
            ("TRUE", True),
        ]:
            with patch.dict(os.environ, ONYX_CHAT_HARNESS_V2=value):
                self.assertEqual(self.enabled(), expected)
                self.assertEqual(
                    request_harness_enabled(self.req, self.session, 1), expected
                )

    def test_unsupported_modes_keep_legacy(self):
        cases = [
            (self.req, "deep_research", True),
            (self.req, "file_descriptors", [1]),
            (self.req, "additional_context", "browser tab"),
            (self.setup, "chat_session_project_id", 1),
            (self.setup.extracted_context_files, "file_metadata", [1]),
            (self.setup.search_params, "project_id_filter", 1),
            (self.setup.search_params, "persona_id_filter", 1),
            (self.setup, "incognito_record_mode", "standard"),
            (self.setup, "forced_tool_id", 1),
        ]
        with patch.dict(os.environ, ONYX_CHAT_HARNESS_V2="true"):
            for obj, key, value in cases:
                with self.subTest(key=key), patch.object(obj, key, value):
                    self.assertFalse(self.enabled())
            self.assertFalse(chat_harness_enabled(self.setup, 2, self.tools))
            self.assertFalse(chat_harness_enabled(self.setup, 1, []))
            self.assertFalse(chat_harness_enabled(self.setup, 1, [object()]))


if __name__ == "__main__":
    unittest.main()
