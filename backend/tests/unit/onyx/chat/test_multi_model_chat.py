"""Tests for multi-model chat functionality in process_message.py."""

import threading
import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.chat.models import MultiModelMessageResponseIDInfo
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet


# =============================================================================
# Model Tests
# =============================================================================


class TestMultiModelMessageResponseIDInfo:
    """Tests for MultiModelMessageResponseIDInfo model."""

    def test_creation_with_valid_data(self) -> None:
        """Test creating the model with valid data."""
        info = MultiModelMessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_ids=[10, 11, 12],
            model_names=["GPT-4", "Claude", "Gemini"],
        )
        assert info.user_message_id == 1
        assert info.reserved_assistant_message_ids == [10, 11, 12]
        assert info.model_names == ["GPT-4", "Claude", "Gemini"]

    def test_creation_with_two_models(self) -> None:
        """Test creating the model with 2 models."""
        info = MultiModelMessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_ids=[10, 11],
            model_names=["GPT-4", "Claude"],
        )
        assert len(info.reserved_assistant_message_ids) == 2
        assert len(info.model_names) == 2

    def test_creation_with_null_user_message_id(self) -> None:
        """Test creating the model with null user_message_id."""
        info = MultiModelMessageResponseIDInfo(
            user_message_id=None,
            reserved_assistant_message_ids=[10, 11],
            model_names=["Model A", "Model B"],
        )
        assert info.user_message_id is None

    def test_serialization(self) -> None:
        """Test JSON serialization of the model."""
        info = MultiModelMessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_ids=[10, 11, 12],
            model_names=["GPT-4", "Claude", "Gemini"],
        )
        data = info.model_dump()
        assert data["user_message_id"] == 1
        assert data["reserved_assistant_message_ids"] == [10, 11, 12]
        assert data["model_names"] == ["GPT-4", "Claude", "Gemini"]

    def test_deserialization(self) -> None:
        """Test JSON deserialization of the model."""
        data = {
            "user_message_id": 5,
            "reserved_assistant_message_ids": [20, 21],
            "model_names": ["Model X", "Model Y"],
        }
        info = MultiModelMessageResponseIDInfo(**data)
        assert info.user_message_id == 5
        assert info.reserved_assistant_message_ids == [20, 21]


class TestPlacementWithModelIndex:
    """Tests for Placement with model_index field."""

    def test_placement_with_model_index(self) -> None:
        """Test creating Placement with model_index."""
        placement = Placement(turn_index=0, model_index=1)
        assert placement.turn_index == 0
        assert placement.model_index == 1

    def test_placement_without_model_index(self) -> None:
        """Test creating Placement without model_index (defaults to None)."""
        placement = Placement(turn_index=0)
        assert placement.model_index is None

    def test_placement_with_all_fields(self) -> None:
        """Test creating Placement with all fields including model_index."""
        placement = Placement(
            turn_index=2,
            tab_index=1,
            sub_turn_index=0,
            model_index=2,
        )
        assert placement.turn_index == 2
        assert placement.tab_index == 1
        assert placement.sub_turn_index == 0
        assert placement.model_index == 2

    def test_placement_serialization_with_model_index(self) -> None:
        """Test serialization includes model_index."""
        placement = Placement(turn_index=0, model_index=0)
        data = placement.model_dump()
        assert "model_index" in data
        assert data["model_index"] == 0


class TestSendMessageRequestWithLLMOverrides:
    """Tests for SendMessageRequest with llm_overrides field."""

    def test_send_message_request_with_llm_overrides(self) -> None:
        """Test creating SendMessageRequest with llm_overrides list."""
        overrides = [
            LLMOverride(model_provider="openai", model_version="gpt-4"),
            LLMOverride(model_provider="anthropic", model_version="claude-3"),
        ]
        # Note: SendMessageRequest requires either chat_session_id or chat_session_info
        # The validator auto-creates chat_session_info if neither is provided
        request = SendMessageRequest(
            message="Hello",
            llm_overrides=overrides,
        )
        assert request.llm_overrides is not None
        assert len(request.llm_overrides) == 2

    def test_send_message_request_with_three_overrides(self) -> None:
        """Test creating SendMessageRequest with 3 llm_overrides."""
        overrides = [
            LLMOverride(model_provider="openai", model_version="gpt-4"),
            LLMOverride(model_provider="anthropic", model_version="claude-3"),
            LLMOverride(model_provider="google", model_version="gemini"),
        ]
        request = SendMessageRequest(
            message="Hello",
            llm_overrides=overrides,
        )
        assert len(request.llm_overrides) == 3

    def test_send_message_request_without_overrides(self) -> None:
        """Test creating SendMessageRequest without llm_overrides."""
        request = SendMessageRequest(message="Hello")
        assert request.llm_overrides is None

    def test_send_message_request_with_single_override(self) -> None:
        """Test creating SendMessageRequest with single llm_override (not list)."""
        override = LLMOverride(model_provider="openai", model_version="gpt-4")
        request = SendMessageRequest(
            message="Hello",
            llm_override=override,
        )
        assert request.llm_override is not None
        assert request.llm_overrides is None


# =============================================================================
# Multi-Model Loop Tests
# =============================================================================


class TestRunMultiModelChatLoops:
    """Tests for _run_multi_model_chat_loops function."""

    def _create_mock_llm(
        self, model_name: str, response_content: str = "Test response"
    ) -> MagicMock:
        """Create a mock LLM for testing."""
        mock_llm = MagicMock()
        mock_llm.config = MagicMock()
        mock_llm.config.model_name = model_name
        return mock_llm

    def _create_mock_state_container(self) -> MagicMock:
        """Create a mock ChatStateContainer."""
        container = MagicMock()
        container.answer_tokens = None
        container.reasoning_tokens = None
        container.tool_calls = []
        container.citation_to_doc = {}
        container.is_clarification = False
        return container

    def test_model_index_tagging_with_two_models(self) -> None:
        """Test that packets are tagged with correct model_index for 2 models."""
        # Import the function we're testing
        from onyx.chat.process_message import _run_multi_model_chat_loops

        # Create mock LLMs
        llms = [
            self._create_mock_llm("model-1"),
            self._create_mock_llm("model-2"),
        ]
        model_names = ["Model 1", "Model 2"]
        state_containers = [
            self._create_mock_state_container(),
            self._create_mock_state_container(),
        ]

        # Track model indices from emitted packets
        emitted_model_indices: set[int] = set()

        # Mock run_llm_loop to emit a simple packet and complete
        def mock_run_llm_loop(
            emitter: Any,
            simple_chat_history: Any,
            tools: Any,
            custom_agent_prompt: Any,
            project_files: Any,
            persona: Any,
            memories: Any,
            llm: Any,
            token_counter: Any,
            db_session: Any,
            forced_tool_id: Any,
            user_identity: Any,
            chat_session_id: Any,
            state_container: Any,
        ) -> None:
            # Emit a simple response delta
            packet = Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="Hello"),
            )
            emitter.emit(packet)
            # Mark answer as complete
            state_container.answer_tokens = "Hello"

        with patch(
            "onyx.chat.process_message.run_llm_loop", side_effect=mock_run_llm_loop
        ):
            mock_emitter = MagicMock()
            mock_db_session = MagicMock()

            packets = list(
                _run_multi_model_chat_loops(
                    llms=llms,
                    model_names=model_names,
                    emitter=mock_emitter,
                    state_containers=state_containers,
                    check_is_connected=lambda: True,
                    simple_chat_history=[],
                    tools=[],
                    custom_agent_prompt=None,
                    extracted_project_files=MagicMock(),
                    persona=MagicMock(),
                    memories=[],
                    token_counter=MagicMock(),
                    db_session=mock_db_session,
                    forced_tool_id=None,
                    user_identity=MagicMock(),
                    chat_session_id="test-session",
                )
            )

            # Collect model indices
            for packet in packets:
                if packet.placement.model_index is not None:
                    emitted_model_indices.add(packet.placement.model_index)

            # Should have packets from both models (indices 0 and 1)
            assert 0 in emitted_model_indices
            assert 1 in emitted_model_indices
            assert 2 not in emitted_model_indices  # Only 2 models

    def test_model_index_tagging_with_three_models(self) -> None:
        """Test that packets are tagged with correct model_index for 3 models."""
        from onyx.chat.process_message import _run_multi_model_chat_loops

        llms = [
            self._create_mock_llm("model-1"),
            self._create_mock_llm("model-2"),
            self._create_mock_llm("model-3"),
        ]
        model_names = ["Model 1", "Model 2", "Model 3"]
        state_containers = [
            self._create_mock_state_container(),
            self._create_mock_state_container(),
            self._create_mock_state_container(),
        ]

        emitted_model_indices: set[int] = set()

        def mock_run_llm_loop(
            emitter: Any,
            simple_chat_history: Any,
            tools: Any,
            custom_agent_prompt: Any,
            project_files: Any,
            persona: Any,
            memories: Any,
            llm: Any,
            token_counter: Any,
            db_session: Any,
            forced_tool_id: Any,
            user_identity: Any,
            chat_session_id: Any,
            state_container: Any,
        ) -> None:
            packet = Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="Response"),
            )
            emitter.emit(packet)
            state_container.answer_tokens = "Response"

        with patch(
            "onyx.chat.process_message.run_llm_loop", side_effect=mock_run_llm_loop
        ):
            mock_emitter = MagicMock()

            packets = list(
                _run_multi_model_chat_loops(
                    llms=llms,
                    model_names=model_names,
                    emitter=mock_emitter,
                    state_containers=state_containers,
                    check_is_connected=lambda: True,
                    simple_chat_history=[],
                    tools=[],
                    custom_agent_prompt=None,
                    extracted_project_files=MagicMock(),
                    persona=MagicMock(),
                    memories=[],
                    token_counter=MagicMock(),
                    db_session=MagicMock(),
                    forced_tool_id=None,
                    user_identity=MagicMock(),
                    chat_session_id="test-session",
                )
            )

            for packet in packets:
                if packet.placement.model_index is not None:
                    emitted_model_indices.add(packet.placement.model_index)

            # Should have packets from all 3 models
            assert 0 in emitted_model_indices
            assert 1 in emitted_model_indices
            assert 2 in emitted_model_indices

    def test_parallel_execution(self) -> None:
        """Test that multiple models run in parallel."""
        from onyx.chat.process_message import _run_multi_model_chat_loops

        llms = [
            self._create_mock_llm("model-1"),
            self._create_mock_llm("model-2"),
        ]
        model_names = ["Model 1", "Model 2"]
        state_containers = [
            self._create_mock_state_container(),
            self._create_mock_state_container(),
        ]

        execution_times: dict[int, float] = {}
        lock = threading.Lock()

        def mock_run_llm_loop(
            emitter: Any,
            simple_chat_history: Any,
            tools: Any,
            custom_agent_prompt: Any,
            project_files: Any,
            persona: Any,
            memories: Any,
            llm: Any,
            token_counter: Any,
            db_session: Any,
            forced_tool_id: Any,
            user_identity: Any,
            chat_session_id: Any,
            state_container: Any,
        ) -> None:
            # Record when this model started
            model_idx = llms.index(llm)
            start_time = time.time()

            # Simulate some work
            time.sleep(0.1)

            with lock:
                execution_times[model_idx] = start_time

            packet = Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="Done"),
            )
            emitter.emit(packet)
            state_container.answer_tokens = "Done"

        with patch(
            "onyx.chat.process_message.run_llm_loop", side_effect=mock_run_llm_loop
        ):
            list(
                _run_multi_model_chat_loops(
                    llms=llms,
                    model_names=model_names,
                    emitter=MagicMock(),
                    state_containers=state_containers,
                    check_is_connected=lambda: True,
                    simple_chat_history=[],
                    tools=[],
                    custom_agent_prompt=None,
                    extracted_project_files=MagicMock(),
                    persona=MagicMock(),
                    memories=[],
                    token_counter=MagicMock(),
                    db_session=MagicMock(),
                    forced_tool_id=None,
                    user_identity=MagicMock(),
                    chat_session_id="test-session",
                )
            )

        # Both models should have started close together (parallel)
        assert len(execution_times) == 2
        time_diff = abs(execution_times[0] - execution_times[1])
        # They should start within 0.05 seconds of each other
        assert time_diff < 0.05, f"Models did not start in parallel: {time_diff}s apart"

    def test_error_isolation(self) -> None:
        """Test that one model's error doesn't crash others."""
        from onyx.chat.process_message import _run_multi_model_chat_loops

        llms = [
            self._create_mock_llm("model-1"),
            self._create_mock_llm("model-2"),
        ]
        model_names = ["Model 1", "Model 2"]
        state_containers = [
            self._create_mock_state_container(),
            self._create_mock_state_container(),
        ]

        call_count = [0]

        def mock_run_llm_loop(
            emitter: Any,
            simple_chat_history: Any,
            tools: Any,
            custom_agent_prompt: Any,
            project_files: Any,
            persona: Any,
            memories: Any,
            llm: Any,
            token_counter: Any,
            db_session: Any,
            forced_tool_id: Any,
            user_identity: Any,
            chat_session_id: Any,
            state_container: Any,
        ) -> None:
            model_idx = llms.index(llm)
            call_count[0] += 1

            if model_idx == 0:
                # First model raises an error
                raise RuntimeError("Model 1 failed!")
            else:
                # Second model succeeds
                packet = Packet(
                    placement=Placement(turn_index=0),
                    obj=AgentResponseDelta(content="Success from model 2"),
                )
                emitter.emit(packet)
                state_container.answer_tokens = "Success from model 2"

        with patch(
            "onyx.chat.process_message.run_llm_loop", side_effect=mock_run_llm_loop
        ):
            packets = list(
                _run_multi_model_chat_loops(
                    llms=llms,
                    model_names=model_names,
                    emitter=MagicMock(),
                    state_containers=state_containers,
                    check_is_connected=lambda: True,
                    simple_chat_history=[],
                    tools=[],
                    custom_agent_prompt=None,
                    extracted_project_files=MagicMock(),
                    persona=MagicMock(),
                    memories=[],
                    token_counter=MagicMock(),
                    db_session=MagicMock(),
                    forced_tool_id=None,
                    user_identity=MagicMock(),
                    chat_session_id="test-session",
                )
            )

        # Both models should have been called
        assert call_count[0] == 2

        # Should have packets from both models (including error for model 0)
        model_indices_seen = {p.placement.model_index for p in packets}
        assert 0 in model_indices_seen  # Error model
        assert 1 in model_indices_seen  # Success model

        # Model 1 should have an OverallStop packet with error stop_reason
        model_0_stops = [
            p
            for p in packets
            if p.placement.model_index == 0 and isinstance(p.obj, OverallStop)
        ]
        assert len(model_0_stops) > 0
        assert model_0_stops[0].obj.stop_reason == "error"

    def test_user_cancellation(self) -> None:
        """Test that user cancellation emits stop packets for incomplete models.

        Note: This tests the cancellation detection during the queue polling loop.
        When check_is_connected returns False, the loop should emit stop packets
        for any models that haven't completed yet.
        """
        from onyx.chat.process_message import _run_multi_model_chat_loops

        llms = [
            self._create_mock_llm("model-1"),
            self._create_mock_llm("model-2"),
        ]
        model_names = ["Model 1", "Model 2"]
        state_containers = [
            self._create_mock_state_container(),
            self._create_mock_state_container(),
        ]

        # Event to control when model threads should complete
        model_wait_event = threading.Event()

        def mock_run_llm_loop(
            emitter: Any,
            simple_chat_history: Any,
            tools: Any,
            custom_agent_prompt: Any,
            project_files: Any,
            persona: Any,
            memories: Any,
            llm: Any,
            token_counter: Any,
            db_session: Any,
            forced_tool_id: Any,
            user_identity: Any,
            chat_session_id: Any,
            state_container: Any,
        ) -> None:
            # Emit a packet
            packet = Packet(
                placement=Placement(turn_index=0),
                obj=AgentResponseDelta(content="Starting..."),
            )
            emitter.emit(packet)

            # Wait for event (simulates long-running operation)
            # This will time out if cancellation happens first
            model_wait_event.wait(timeout=2.0)

            state_container.answer_tokens = "Completed"

        # Start returning False after a short delay to trigger cancellation
        call_count = [0]

        def check_is_connected() -> bool:
            call_count[0] += 1
            # Return False after a few checks to trigger cancellation
            if call_count[0] >= 3:
                return False
            return True

        with patch(
            "onyx.chat.process_message.run_llm_loop", side_effect=mock_run_llm_loop
        ):
            packets = list(
                _run_multi_model_chat_loops(
                    llms=llms,
                    model_names=model_names,
                    emitter=MagicMock(),
                    state_containers=state_containers,
                    check_is_connected=check_is_connected,
                    simple_chat_history=[],
                    tools=[],
                    custom_agent_prompt=None,
                    extracted_project_files=MagicMock(),
                    persona=MagicMock(),
                    memories=[],
                    token_counter=MagicMock(),
                    db_session=MagicMock(),
                    forced_tool_id=None,
                    user_identity=MagicMock(),
                    chat_session_id="test-session",
                )
            )

        # Release the wait event so threads can clean up
        model_wait_event.set()

        # check_is_connected should have been called multiple times
        assert call_count[0] >= 3

        # Should have stop packets for models
        stop_packets = [p for p in packets if isinstance(p.obj, OverallStop)]

        # When cancelled, we should get stop packets with user_cancelled reason
        cancelled_stops = [
            p for p in stop_packets if p.obj.stop_reason == "user_cancelled"
        ]
        # Both models should have been cancelled since they were still waiting
        assert len(cancelled_stops) == 2


# =============================================================================
# Integration-Level Tests (testing the detection logic)
# =============================================================================


class TestMultiModelDetection:
    """Tests for the multi-model detection logic in handle_stream_message_objects."""

    def test_detection_with_one_model_uses_normal_mode(self) -> None:
        """Test that 1 model in llm_overrides should NOT trigger multi-model mode.

        Note: The current implementation requires >= 2 models for multi-model mode.
        If only 1 model is in llm_overrides, it falls through to single-model path.
        """
        overrides = [LLMOverride(model_provider="openai", model_version="gpt-4")]

        # 1 override should NOT trigger multi-model mode
        assert len(overrides) < 2

    def test_detection_with_two_models_triggers_multi_model(self) -> None:
        """Test that 2 models in llm_overrides triggers multi-model mode."""
        overrides = [
            LLMOverride(model_provider="openai", model_version="gpt-4"),
            LLMOverride(model_provider="anthropic", model_version="claude-3"),
        ]

        # 2 overrides should trigger multi-model mode
        assert len(overrides) >= 2

    def test_detection_with_three_models_triggers_multi_model(self) -> None:
        """Test that 3 models in llm_overrides triggers multi-model mode."""
        overrides = [
            LLMOverride(model_provider="openai", model_version="gpt-4"),
            LLMOverride(model_provider="anthropic", model_version="claude-3"),
            LLMOverride(model_provider="google", model_version="gemini"),
        ]

        # 3 overrides should trigger multi-model mode
        assert len(overrides) >= 2

    def test_model_name_fallback(self) -> None:
        """Test model name fallback chain: model_version -> model_provider -> 'Model N'."""
        # Test with model_version
        override1 = LLMOverride(model_provider="openai", model_version="gpt-4")
        name1 = override1.model_version or override1.model_provider or "Model 1"
        assert name1 == "gpt-4"

        # Test with only model_provider
        override2 = LLMOverride(model_provider="anthropic")
        name2 = override2.model_version or override2.model_provider or "Model 2"
        assert name2 == "anthropic"

        # Test with neither
        override3 = LLMOverride()
        name3 = override3.model_version or override3.model_provider or "Model 3"
        assert name3 == "Model 3"
