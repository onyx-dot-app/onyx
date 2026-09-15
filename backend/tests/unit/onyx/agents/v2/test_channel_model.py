import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from onyx.agents.v2.channel_model import (
    ChannelDecisionModel,
    NativeChannelLLM,
    PhasedMessage,
    convert_response,
)
from onyx.agents.v2.models import HarnessPolicy, ModelDecision, UsageSnapshot
from onyx.agents.v2.runner import AgentHarness
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import ReasoningEffort, SystemMessage, UserMessage


def msg(phase, text):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "phase": phase,
        "content": [{"type": "output_text", "text": text}],
    }


def response(items, status="completed"):
    return convert_response(
        NS(
            id="resp_1",
            created_at=1,
            status=status,
            output=items,
            usage=NS(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                input_tokens_details=NS(cached_tokens=2),
            ),
        )
    )


CALL = {
    "type": "function_call",
    "call_id": "call_1",
    "name": "internal_search",
    "arguments": '{"query":"limits"}',
}


class ChannelTests(unittest.TestCase):
    def test_commentary_does_not_complete(self):
        m = ChannelDecisionModel(Mock())
        d = m.parse(response([msg("commentary", "Searching")]))
        self.assertIsNone(d.outcome)
        self.assertTrue(d.continue_turn)
        self.assertEqual(d.answer, "")

    def test_preamble_does_not_hide_tool_call(self):
        seen = []
        m = ChannelDecisionModel(Mock(), seen.append)
        d = m.parse(response([msg("commentary", "Searching"), CALL]))
        self.assertEqual(d.calls[0].name, "internal_search")
        self.assertIsNone(d.outcome)
        self.assertEqual(seen[0].phase, "commentary")

    def test_final_excludes_commentary_and_reasoning(self):
        m = ChannelDecisionModel(Mock())
        d = m.parse(
            response(
                [
                    msg("commentary", "Checking"),
                    {"type": "reasoning", "summary": [{"text": "private"}]},
                    msg("final_answer", "Answer [1]"),
                ]
            )
        )
        self.assertEqual(d.outcome, "completed")
        self.assertEqual(d.answer, "Answer [1]")

    def test_unknown_phase_compatibility(self):
        m = ChannelDecisionModel(Mock())
        self.assertEqual(m.parse(response([msg(None, "Answer")])).outcome, "completed")
        self.assertEqual(
            m.parse(response([msg(None, "Preamble"), CALL])).calls[0].name,
            "internal_search",
        )

    def test_incomplete_commentary_never_becomes_answer(self):
        d = ChannelDecisionModel(Mock()).parse(
            response([msg("commentary", "Working")], "incomplete")
        )
        self.assertEqual(d.outcome, "partial")
        self.assertEqual(d.answer, "")

    def test_final_and_tool_cannot_complete(self):
        d = ChannelDecisionModel(Mock()).parse(
            response([msg("final_answer", "Answer"), CALL])
        )
        self.assertEqual(d.outcome, "partial")

    def test_progress_only_is_bounded(self):
        m = ChannelDecisionModel(Mock())
        for _ in range(2):
            self.assertTrue(
                m.parse(response([msg("commentary", "Working")])).continue_turn
            )
        d = m.parse(response([msg("commentary", "Working")]))
        self.assertEqual(d.outcome, "partial")
        self.assertEqual(d.answer, "")

    def test_phase_preserved_in_next_prompt(self):
        llm = Mock()
        llm.invoke.side_effect = [
            response([msg("commentary", "Checking")]),
            response([msg("final_answer", "Done")]),
        ]
        m = ChannelDecisionModel(llm)
        args = dict(
            task="Question",
            context="{}",
            tools=[],
            remaining_seconds=100,
            remaining_tokens=10000,
            max_output_tokens=100,
        )
        m.decide(**args)
        m.decide(**args)
        replay = llm.invoke.call_args.kwargs["prompt"][1]
        self.assertEqual(replay.phase, "commentary")
        self.assertEqual(replay.content, "Checking")

    def test_native_wire_reasoning_and_phases(self):
        c = Mock()
        c.responses.create.return_value = NS(
            id="resp_1",
            created_at=1,
            status="completed",
            output=[msg("final_answer", "Done")],
            usage=None,
        )
        configured = Mock()
        configured.config = LLMConfig(
            model_provider="openai",
            model_name="gpt-5.6-sol",
            api_key="fake",
            temperature=0,
            max_input_tokens=100000,
        )
        llm = NativeChannelLLM(configured, client=c)
        llm.invoke(
            prompt=[
                SystemMessage(content="rules"),
                PhasedMessage(content="Searching", phase="commentary"),
                UserMessage(content="state"),
            ],
            reasoning_effort=ReasoningEffort.OFF,
            max_tokens=100,
        )
        kw = c.responses.create.call_args.kwargs
        self.assertEqual(kw["reasoning"], {"effort": "none"})
        self.assertEqual(kw["input"][1]["phase"], "commentary")
        self.assertNotIn("phase", kw["input"][2])
        self.assertFalse(kw["store"])

    def test_runner_continues_then_finishes(self):
        m = Mock()
        m.decide.side_effect = [
            ModelDecision(continue_turn=True),
            ModelDecision(outcome="completed", answer="Done"),
        ]
        h = AgentHarness(
            model=m,
            tools=[],
            policy=HarnessPolicy(duration_mode="soft"),
            usage=UsageSnapshot,
        )
        r = h.run("Question")
        self.assertEqual(r.answer, "Done")
        self.assertEqual(r.outcome, "completed")
        self.assertEqual(m.decide.call_count, 2)


if __name__ == "__main__":
    unittest.main()
