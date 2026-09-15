import unittest

from onyx.agents.v2.search_expansion_context import SearchExpansionContext


class SearchExpansionContextTests(unittest.TestCase):
    def test_default_preserves_objective_before_user_anchor(self):
        messages = SearchExpansionContext().messages(
            "Original task", "Current objective", True
        )
        self.assertEqual(messages[-1], ("user", "Original task"))
        self.assertIn("Current objective", messages[0][1])

    def test_objective_survives_last_user_history_slice(self):
        for strategy in ["legacy", "objective", "complementary"]:
            history = SearchExpansionContext(strategy).messages(
                "Original task", "Follow-up GIF clue", True
            )
            last = max(i for i, (role, _) in enumerate(history) if role == "user")
            visible = history[:last] + [history[last]]
            self.assertEqual(
                any("GIF clue" in text for _, text in visible), strategy != "legacy"
            )
            self.assertEqual(history[last], ("user", "Original task"))

    def test_completed_queries_and_evidence_available_only_in_complementary(self):
        for strategy in ["legacy", "objective", "complementary"]:
            state = SearchExpansionContext(strategy)
            state.observe(
                "First objective",
                ["executed phrase"],
                [
                    {
                        "semantic_identifier": "Known artifact",
                        "blurb": "Observed mismatch",
                    }
                ],
            )
            text = str(state.messages("Question", "Second objective", True))
            self.assertEqual("executed phrase" in text, strategy == "complementary")
            self.assertEqual("Observed mismatch" in text, strategy == "complementary")

    def test_history_is_bounded_and_task_local(self):
        state = SearchExpansionContext("complementary")
        for i in range(10):
            state.observe(
                "objective" + str(i), ["x" * 1000] * 20, [{"content": "y" * 2000}] * 20
            )
        text = str(state.messages("Question", "Next", True))
        self.assertNotIn("objective6", text)
        self.assertIn("objective7", text)
        self.assertLess(len(text), 11000)
        self.assertNotIn(
            "objective7",
            str(
                SearchExpansionContext("complementary").messages(
                    "Question", "Next", True
                )
            ),
        )

    def test_unanchored_legacy_callers_unchanged(self):
        for strategy in ["legacy", "objective", "complementary"]:
            self.assertEqual(
                SearchExpansionContext(strategy).messages("Task", "Objective", False),
                [("user", "Objective")],
            )

    def test_invalid_strategy_rejected(self):
        with self.assertRaises(ValueError):
            SearchExpansionContext("typo")  # ty: ignore[invalid-argument-type] Invalid input is the test subject.


if __name__ == "__main__":
    unittest.main()
