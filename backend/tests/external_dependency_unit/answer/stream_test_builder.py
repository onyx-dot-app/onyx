from __future__ import annotations

from collections.abc import Iterator

from onyx.chat.models import AnswerStreamPart
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from tests.external_dependency_unit.answer.stream_test_assertions import (
    assert_answer_stream_part_correct,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_packet_with_agent_response_delta,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_packet_with_reasoning_delta,
)
from tests.external_dependency_unit.answer.stream_test_utils import create_placement
from tests.external_dependency_unit.mock_llm import LLMResponse
from tests.external_dependency_unit.mock_llm import MockLLMController


class StreamTestBuilder:
    def __init__(self, llm_controller: MockLLMController) -> None:
        self._llm_controller = llm_controller

        # List of (expected_packet, forward_count) tuples
        self._expected_packets_queue: list[tuple[Packet, int]] = []

    def add_response(self, response: LLMResponse) -> StreamTestBuilder:
        self._llm_controller.add_response(response)

        return self

    def add_responses_together(self, *responses: LLMResponse) -> StreamTestBuilder:
        """Add multiple responses that should be emitted together in the same tick."""
        self._llm_controller.add_responses_together(*responses)

        return self

    def expect(
        self, expected_pkt: Packet, forward: int | bool = True
    ) -> StreamTestBuilder:
        """
        Add an expected packet to the queue.

        Args:
            expected_pkt: The packet to expect
            forward: Number of tokens to forward before expecting this packet.
                     True = 1 token, False = 0 tokens, int = that many tokens.
        """
        forward_count = 1 if forward is True else (0 if forward is False else forward)
        self._expected_packets_queue.append((expected_pkt, forward_count))

        return self

    def expect_packets(
        self, packets: list[Packet], forward: int | bool = True
    ) -> StreamTestBuilder:
        """
        Add multiple expected packets to the queue.

        Args:
            packets: List of packets to expect
            forward: Number of tokens to forward before expecting EACH packet.
                     True = 1 token per packet, False = 0 tokens, int = that many tokens per packet.
        """
        forward_count = 1 if forward is True else (0 if forward is False else forward)
        for pkt in packets:
            self._expected_packets_queue.append((pkt, forward_count))

        return self

    def expect_reasoning(
        self,
        reasoning_tokens: list[str],
        turn_index: int,
    ) -> StreamTestBuilder:
        return (
            self.expect(
                Packet(
                    placement=create_placement(turn_index),
                    obj=ReasoningStart(),
                )
            )
            .expect_packets(
                [
                    create_packet_with_reasoning_delta(token, turn_index)
                    for token in reasoning_tokens
                ]
            )
            .expect(
                Packet(
                    placement=create_placement(turn_index),
                    obj=ReasoningDone(),
                )
            )
        )

    def expect_agent_response(
        self,
        answer_tokens: list[str],
        turn_index: int,
        final_documents: list[SearchDoc] | None = None,
    ) -> StreamTestBuilder:
        return (
            self.expect(
                Packet(
                    placement=create_placement(turn_index),
                    obj=AgentResponseStart(
                        final_documents=final_documents,
                    ),
                )
            )
            .expect_packets(
                [
                    create_packet_with_agent_response_delta(token, turn_index)
                    for token in answer_tokens
                ]
            )
            .expect(
                Packet(
                    placement=create_placement(turn_index),
                    obj=OverallStop(),
                )
            )
        )

    def run_and_validate(self, stream: Iterator[AnswerStreamPart]) -> None:
        while self._expected_packets_queue:
            expected_pkt, forward_count = self._expected_packets_queue.pop(0)
            if forward_count > 0:
                self._llm_controller.forward(forward_count)
            received_pkt = next(stream)

            assert_answer_stream_part_correct(received_pkt, expected_pkt)
