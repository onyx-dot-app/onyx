import re
import unittest
from types import SimpleNamespace as NS
from typing import Any, cast
from unittest.mock import Mock

from onyx.agents.v2.channel_model import ChannelDecisionModel, NativeChannelLLM
from onyx.agents.v2.llm import TaskCancelled
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import UserMessage


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def __iter__(self):
        return iter(self.events)


def item(phase="final_answer", text="Hello [1]"):
    return dict(
        id="m",
        type="message",
        role="assistant",
        phase=phase,
        content=[dict(type="output_text", text=text)],
    )


def terminal(items=None, status="completed"):
    return NS(
        type="response." + status,
        response=NS(
            id="r",
            created_at=1,
            status=status,
            output=items or [item()],
            usage=NS(
                input_tokens=20,
                output_tokens=4,
                total_tokens=24,
                input_tokens_details=NS(cached_tokens=2),
            ),
        ),
    )


def added(phase="final_answer", index=0):
    return NS(
        type="response.output_item.added",
        output_index=index,
        item=NS(type="message", role="assistant", phase=phase),
    )


def delta(text, index=0, kind="response.output_text.delta"):
    return NS(type=kind, output_index=index, delta=text)


def model(events, seen, cancelled=lambda: False):
    client = Mock()
    stream = FakeStream(events)
    client.responses.create.return_value = stream
    configured = Mock()
    configured.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5.6-sol",
        api_key="fake",
        temperature=0,
        max_input_tokens=100000,
    )
    return (
        NativeChannelLLM(
            configured, client=client, on_final_delta=seen.append, cancelled=cancelled
        ),
        client,
        stream,
    )


class StreamingTests(unittest.TestCase):
    def test_text_arrives_before_terminal_and_usage_is_preserved(self):
        seen = []

        def events():
            yield added()
            yield delta("Hello [")
            self.assertEqual(seen, ["Hello ["])
            yield delta("1]")
            yield terminal()

        llm, client, stream = model(events(), seen)
        response = llm.invoke([UserMessage(content="Question")], max_tokens=100)
        self.assertEqual("".join(seen), "Hello [1]")
        self.assertEqual(response.usage.total_tokens, 24)
        self.assertTrue(client.responses.create.call_args.kwargs["stream"])
        self.assertEqual(
            client.responses.create.call_args.kwargs["reasoning"], {"effort": "none"}
        )
        self.assertTrue(stream.closed)
        self.assertIsNotNone(llm.stream_metrics[0]["first_final_delta_s"])

    def test_commentary_and_reasoning_do_not_stream_as_final(self):
        seen = []
        events = [
            added("commentary"),
            delta("Working"),
            delta("private", kind="response.reasoning_text.delta"),
            added(index=1),
            delta("Hello [1]", index=1),
            terminal([item("commentary", "Working"), item()]),
        ]
        llm, _, _ = model(events, seen)
        response = llm.invoke([UserMessage(content="Question")])
        decision = ChannelDecisionModel(Mock()).parse(response)
        self.assertEqual(seen, ["Hello [1]"])
        self.assertEqual(decision.answer, "Hello [1]")

    def test_missing_phase_waits_for_compatibility_parser(self):
        seen = []
        llm, _, _ = model(
            [added(None), delta("Hello [1]"), terminal([item(None)])], seen
        )
        response = llm.invoke([UserMessage(content="Question")])
        self.assertEqual(seen, [])
        self.assertEqual(
            ChannelDecisionModel(Mock()).parse(response).answer, "Hello [1]"
        )

    def test_cancel_closes_stream_and_stops_deltas(self):
        seen = []
        llm, _, stream = model(
            [added(), delta("Hello"), delta("more"), terminal()],
            seen,
            lambda: bool(seen),
        )
        with self.assertRaises(TaskCancelled):
            llm.invoke([UserMessage(content="Question")])
        self.assertEqual(seen, ["Hello"])
        self.assertTrue(stream.closed)

    def test_incomplete_is_partial(self):
        seen = []
        llm, _, _ = model(
            [added(), delta("Hello [1]"), terminal(status="incomplete")], seen
        )
        result = ChannelDecisionModel(Mock()).parse(
            llm.invoke([UserMessage(content="Question")])
        )
        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.answer, "Hello [1]")

    def test_abrupt_end_is_not_success(self):
        seen = []
        llm, _, stream = model([added(), delta("Hello")], seen)
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            llm.invoke([UserMessage(content="Question")])
        self.assertTrue(stream.closed)

    def test_multiple_final_items_preserve_separator(self):
        seen = []
        llm, _, _ = model(
            [
                added(),
                delta("First"),
                added(index=1),
                delta("Second", 1),
                terminal([item(text="First"), item(text="Second")]),
            ],
            seen,
        )
        response = llm.invoke([UserMessage(content="Question")])
        self.assertEqual(
            "".join(seen), ChannelDecisionModel(Mock()).parse(response).answer
        )

    def test_refusal_is_visible(self):
        seen = []
        i = item()
        i["content"] = [dict(type="refusal", refusal="Cannot help")]
        llm, _, _ = model(
            [
                added(),
                delta("Cannot help", kind="response.refusal.delta"),
                terminal([i]),
            ],
            seen,
        )
        result = ChannelDecisionModel(Mock()).parse(
            llm.invoke([UserMessage(content="Question")])
        )
        self.assertEqual("".join(seen), result.answer)


class CitationStreamingTests(unittest.TestCase):
    def test_split_citations_match_buffered_rendering(self):
        from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
        from onyx.server.query_and_chat.streaming_models import CitationInfo

        def render(parts, mode):
            processor = DynamicCitationProcessor(citation_mode=mode)
            processor.update_citation_mapping(
                cast(
                    Any,
                    {
                        1: NS(document_id="doc-a", link="https://example.com/a"),
                        2: NS(document_id="doc-b", link="https://example.com/b"),
                    },
                )
            )
            text = []
            citations = []
            for part in [*parts, None]:
                for value in processor.process_token(part):
                    if isinstance(value, CitationInfo):
                        citations.append((value.citation_number, value.document_id))
                    else:
                        text.append(value)
            rendered = "".join(text)
            if mode == CitationMode.REMOVE:
                # Legacy processor cannot retract a space emitted before a later
                # citation-removal event. Compare content, allowing that spacing.
                rendered = re.sub(r" +([,.;])", r"\1", rendered)
            return rendered, citations

        answer = "The limits are documented [1], and explained here [2]. End."
        for mode in [CitationMode.HYPERLINK, CitationMode.REMOVE]:
            baseline = render([answer], mode)
            for split in range(1, len(answer)):
                self.assertEqual(
                    render([answer[:split], answer[split:]], mode), baseline
                )
            self.assertEqual(render(list(answer), mode), baseline)


if __name__ == "__main__":
    unittest.main()
