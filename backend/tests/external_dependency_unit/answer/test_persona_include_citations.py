"""External-dependency-unit tests for the persona-level `include_citations` flag.

These verify that an agent (persona) configured with `include_citations=False`
turns citations off for its answers, and that the persona flag combines with the
per-request `SendMessageRequest.include_citations` flag via a logical AND.

Why we assert on the value passed into `run_llm_loop` rather than only on the
rendered answer: the citation processor only produces inline `[[n]]` links and
`CitationInfo` packets for citation numbers that resolve to a *real* document in
the citation mapping. Populating that mapping deterministically requires a
multi-cycle search-tool flow (LLM emits a tool call -> search returns docs ->
LLM emits an answer that cites them), which is brittle to drive without exact
packet-sequence assertions. Instead we run a single-cycle answer and spy on the
effective `include_citations` value handed to `run_llm_loop` (which selects the
`DynamicCitationProcessor` mode). That value is the single decision point that
governs whether any citation / sources output is emitted, so it is the precise
thing this feature changes. For the disabled case we additionally confirm the
`ChatFullResponse`-shape behavior the feature promises: no `CitationInfo` is
emitted and the `[n]` marker is stripped from the rendered answer.
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat import process_message
from onyx.db.chat import create_chat_session
from onyx.db.persona import upsert_persona
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import tokenise
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse
from tests.external_dependency_unit.mock_llm import use_mock_llm


@pytest.mark.parametrize(
    "persona_include_citations, request_include_citations, expected_effective",
    [
        # Agent config disables citations -> off regardless of the request flag.
        (False, True, False),
        # Request disables citations -> off even when the agent allows them (AND).
        (True, False, False),
        # Both allow citations -> on.
        (True, True, True),
    ],
)
def test_persona_include_citations_controls_citation_generation(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
    persona_include_citations: bool,
    request_include_citations: bool,
    expected_effective: bool,
) -> None:
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(db_session, email_prefix="test_include_citations")

    persona = upsert_persona(
        user=None,  # system persona
        name=f"Citations Persona {uuid.uuid4()}",
        description="Persona for include_citations behavior test",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=True,
        db_session=db_session,
        tool_ids=[],  # no tools -> single LLM answer cycle
        document_set_ids=None,
        is_listed=True,
        default_model_configuration_id=None,
        include_citations=persona_include_citations,
    )

    # Persist the configured flag exactly as requested.
    assert persona.include_citations is persona_include_citations

    chat_session = create_chat_session(
        db_session=db_session,
        description="include_citations test",
        user_id=test_user.id,
        persona_id=persona.id,
    )

    # The answer contains a citation marker so we can confirm it is stripped when
    # citations are disabled.
    answer_tokens = tokenise("Onyx is great [1].")

    with (
        use_mock_llm() as mock_llm,
        patch.object(
            process_message,
            "run_llm_loop",
            wraps=process_message.run_llm_loop,
        ) as spy_run_llm_loop,
    ):
        mock_llm.add_response(LLMAnswerResponse(answer_tokens=answer_tokens))

        request = SendMessageRequest(
            message="Tell me about Onyx",
            chat_session_id=chat_session.id,
            include_citations=request_include_citations,
        )

        answer_stream = process_message.handle_stream_message_objects(
            new_msg_req=request,
            user=test_user,
        )

        # The message-id packet is emitted before the LLM stream is consumed.
        next(answer_stream)
        mock_llm.forward_till_end()

        answer_text = ""
        citation_infos: list[CitationInfo] = []
        for part in answer_stream:
            obj = part.obj if isinstance(part, Packet) else part
            if isinstance(obj, AgentResponseDelta) and obj.content:
                answer_text += obj.content
            elif isinstance(obj, CitationInfo):
                citation_infos.append(obj)

    # The persona and request flags must combine (logical AND) into the value
    # passed to run_llm_loop, which selects the DynamicCitationProcessor mode.
    assert spy_run_llm_loop.call_args is not None
    assert spy_run_llm_loop.call_args.kwargs["include_citations"] is expected_effective

    if not expected_effective:
        # Citations disabled -> no CitationInfo packets and the [n] marker is
        # stripped from the rendered answer (no inline citation, no sources).
        assert citation_infos == []
        assert "[1]" not in answer_text
        assert "[[" not in answer_text
