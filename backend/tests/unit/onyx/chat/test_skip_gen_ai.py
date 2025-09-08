from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from langchain_core.messages import HumanMessage
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from onyx.chat.answer import Answer
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.llm.interfaces import LLM
from onyx.llm.utils import get_max_input_tokens
from onyx.tools.force import ForceUseTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.regression.answer_quality.run_qa import _process_and_write_query_results


@pytest.mark.parametrize(
    "config",
    [
        {
            "skip_gen_ai_answer_generation": True,
            "question": "What is the capital of the moon?",
        },
        {
            "skip_gen_ai_answer_generation": False,
            "question": "What is the capital of the moon but twice?",
        },
    ],
)
@pytest.mark.skip(reason="need to fix")
# TODO (chris): fix this test
def test_skip_gen_ai_answer_generation_flag(
    config: dict[str, Any],
    mock_search_tool: SearchTool,
    answer_style_config: AnswerStyleConfig,
    prompt_config: PromptConfig,
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "onyx.chat.answer.fast_gpu_status_request",
        return_value=True,
    )

    question = config["question"]
    skip_gen_ai_answer_generation = config["skip_gen_ai_answer_generation"]

    model_provider = "gpt-4o-mini"
    model_name = "gpt-4o-mini"

    mock_llm = Mock(spec=LLM)
    mock_llm.config = Mock()
    mock_llm.config.model_name = model_name
    mock_llm.config.max_input_tokens = get_max_input_tokens(
        model_provider=model_provider,
        model_name=model_name,
    )
    mock_llm.stream = Mock()
    mock_llm.stream.return_value = [Mock()]

    # Set up the mock database session
    mock_db_session = Mock(spec=Session)
    mock_query = Mock()
    mock_db_session.query.return_value = mock_query
    mock_query.all.return_value = []  # Return empty list for KGConfig query
    mock_query.distinct.return_value = mock_query

    answer = Answer(
        db_session=mock_db_session,
        answer_style_config=answer_style_config,
        llm=mock_llm,
        fast_llm=mock_llm,
        tools=[mock_search_tool],
        force_use_tool=ForceUseTool(
            tool_name=mock_search_tool.name,
            args={"query": question},
            force_use=True,
        ),
        skip_explicit_tool_calling=True,
        skip_gen_ai_answer_generation=skip_gen_ai_answer_generation,
        persona=None,
        rerank_settings=None,
        prompt_builder=AnswerPromptBuilder(
            user_message=HumanMessage(content=question),
            message_history=[],
            llm_config=mock_llm.config,
            raw_user_query=question,
            raw_user_uploaded_files=[],
        ),
        chat_session_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        current_agent_message_id=0,
    )
    results = list(answer.processed_streamed_output)
    for res in results:
        print(res)

    expected_count = 3 if skip_gen_ai_answer_generation else 4
    assert len(results) == expected_count
    if not skip_gen_ai_answer_generation:
        mock_llm.stream.assert_called_once()
    else:
        mock_llm.stream.assert_not_called()


##### From here down is the client side test that was not working #####


class FinishedTestException(Exception):
    pass


# could not get this to work, it seems like the mock is not being used
# tests that the main run_qa function passes the skip_gen_ai_answer_generation flag to the Answer object
@pytest.mark.parametrize(
    "config, questions",
    [
        (
            {
                "skip_gen_ai_answer_generation": True,
                "output_folder": "./test_output_folder",
                "zipped_documents_file": "./test_docs.jsonl",
                "questions_file": "./test_questions.jsonl",
                "commit_sha": None,
                "launch_web_ui": False,
                "only_retrieve_docs": True,
                "use_cloud_gpu": False,
                "model_server_ip": "PUT_PUBLIC_CLOUD_IP_HERE",
                "model_server_port": "PUT_PUBLIC_CLOUD_PORT_HERE",
                "environment_name": "",
                "env_name": "",
                "limit": None,
            },
            [{"uid": "1", "question": "What is the capital of the moon?"}],
        ),
        (
            {
                "skip_gen_ai_answer_generation": False,
                "output_folder": "./test_output_folder",
                "zipped_documents_file": "./test_docs.jsonl",
                "questions_file": "./test_questions.jsonl",
                "commit_sha": None,
                "launch_web_ui": False,
                "only_retrieve_docs": True,
                "use_cloud_gpu": False,
                "model_server_ip": "PUT_PUBLIC_CLOUD_IP_HERE",
                "model_server_port": "PUT_PUBLIC_CLOUD_PORT_HERE",
                "environment_name": "",
                "env_name": "",
                "limit": None,
            },
            [{"uid": "1", "question": "What is the capital of the moon but twice?"}],
        ),
    ],
)
@pytest.mark.skip(reason="not working")
def test_run_qa_skip_gen_ai(
    config: dict[str, Any], questions: list[dict[str, Any]], mocker: MockerFixture
) -> None:
    mocker.patch(
        "tests.regression.answer_quality.run_qa._initialize_files",
        return_value=("test", questions),
    )

    def arg_checker(question_data: dict, config: dict, question_number: int) -> None:
        assert question_data == questions[0]
        raise FinishedTestException()

    mocker.patch(
        "tests.regression.answer_quality.run_qa._process_question", arg_checker
    )
    with pytest.raises(FinishedTestException):
        _process_and_write_query_results(config)
