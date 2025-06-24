import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from typing import Any

import yaml

from onyx.agents.agent_search.deep_search.main.graph_builder import (
    agent_search_graph_builder,
)
from onyx.agents.agent_search.deep_search.main.states import (
    MainInput as MainInput_a,
)
from onyx.agents.agent_search.run_graph import run_agent_search_graph
from onyx.agents.agent_search.run_graph import run_basic_graph
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import RefinedAnswerImprovement
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamType
from onyx.chat.models import SubQuestionPiece
from onyx.context.search.models import SearchRequest
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.llm.factory import get_default_llms
from onyx.tools.force import ForceUseTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


cwd = os.getcwd()
CONFIG = yaml.safe_load(
    open(f"{cwd}/backend/tests/regression/answer_quality/search_test_config.yaml")
)
INPUT_DIR = CONFIG["agent_test_input_folder"]
OUTPUT_DIR = CONFIG["agent_test_output_folder"]


graph = agent_search_graph_builder()
compiled_graph = graph.compile()
primary_llm, fast_llm = get_default_llms()

# create a local json test data file and use it here


input_file_object = open(
    f"{INPUT_DIR}/agent_test_data.json",
)
output_file = f"{OUTPUT_DIR}/agent_test_output.csv"

csv_output_data: list[list[str]] = []

test_data = json.load(input_file_object)
example_data = test_data["examples"]
example_ids = test_data["example_ids"]

failed_example_ids: list[int] = []

with get_session_with_current_tenant() as db_session:
    output_data: dict[str, Any] = {}

    primary_llm, fast_llm = get_default_llms()

    for example in example_data:
        query_start_time: datetime = datetime.now()
        example_id: int = int(example.get("id"))
        example_question: str = example.get("question")
        if not example_question or not example_id:
            continue
        if len(example_ids) > 0 and example_id not in example_ids:
            continue

        logger.info(f"{query_start_time} -- Processing example {example_id}")

        try:
            example_question = example["question"]
            target_sub_questions = example.get("target_sub_questions", [])
            num_target_sub_questions = len(target_sub_questions)
            search_request = SearchRequest(query=example_question)

            initial_answer_duration: timedelta | None = None
            refined_answer_duration: timedelta | None = None
            base_answer_duration: timedelta | None = None

            logger.debug("\n\nTEST QUERY START\n\n")

            graph = agent_search_graph_builder()
            compiled_graph = graph.compile()
            query_end_time = datetime.now()

            search_request = SearchRequest(
                # query="what can you do with gitlab?",
                # query="What are the guiding principles behind the development of cockroachDB",
                # query="What are the temperatures in Munich, Hawaii, and New York?",
                # query="When was Washington born?",
                # query="What is Onyx?",
                # query="What is the difference between astronomy and astrology?",
                query=example_question,
            )

            answer_tokens: dict[str, list[str]] = defaultdict(list)

            with get_session_with_current_tenant() as db_session:
                config = get_test_config(
                    db_session, primary_llm, fast_llm, search_request
                )
                assert (
                    config.persistence is not None
                ), "set a chat session id to run this test"

                # search_request.persona = get_persona_by_id(1, None, db_session)
                # config.perform_initial_search_path_decision = False
                config.behavior.perform_initial_search_decomposition = True
                input = MainInput_a()

                # Base Flow
                base_flow_start_time: datetime = datetime.now()
                for output in run_basic_graph(config):
                    if isinstance(output, OnyxAnswerPiece):
                        answer_tokens["base_answer"].append(output.answer_piece or "")

                output_data["base_answer"] = "".join(answer_tokens["base_answer"])
                output_data["base_answer_duration"] = (
                    datetime.now() - base_flow_start_time
                )

                # Agent Flow
                agent_flow_start_time: datetime = datetime.now()
                config = get_test_config(
                    db_session,
                    primary_llm,
                    fast_llm,
                    search_request,
                    use_agentic_search=True,
                )

                config.tooling.force_use_tool = ForceUseTool(
                    force_use=True, tool_name=SearchTool._NAME
                )

                tool_responses: list = []

                sub_question_dict_tokens: dict[int, dict[int, str]] = defaultdict(
                    lambda: defaultdict(str)
                )

                for output in run_agent_search_graph(config):
                    if isinstance(output, AgentAnswerPiece):
                        if output.level == 0 and output.level_question_num == 0:
                            answer_tokens["initial"].append(output.answer_piece)
                        elif output.level == 1 and output.level_question_num == 0:
                            answer_tokens["refined"].append(output.answer_piece)
                    elif isinstance(output, SubQuestionPiece):
                        if (
                            output.level is not None
                            and output.level_question_num is not None
                        ):
                            sub_question_dict_tokens[output.level][
                                output.level_question_num
                            ] += output.sub_question
                    elif isinstance(output, StreamStopInfo):
                        if (
                            output.stream_type == StreamType.MAIN_ANSWER
                            and output.level == 0
                        ):
                            initial_answer_duration = (
                                datetime.now() - agent_flow_start_time
                            )
                    elif isinstance(output, RefinedAnswerImprovement):
                        output_data["refined_answer_improves_on_initial_answer"] = str(
                            output.refined_answer_improvement
                        )

                refined_answer_duration = datetime.now() - agent_flow_start_time

                output_data["example_id"] = example_id
                output_data["question"] = example_question
                output_data["initial_answer"] = "".join(answer_tokens["initial"])
                output_data["refined_answer"] = "".join(answer_tokens["refined"])
                output_data["initial_answer_duration"] = initial_answer_duration or ""
                output_data["refined_answer_duration"] = refined_answer_duration

                output_data["initial_sub_questions"] = "\n---\n".join(
                    [x for x in sub_question_dict_tokens[0].values()]
                )
                output_data["refined_sub_questions"] = "\n---\n".join(
                    [x for x in sub_question_dict_tokens[1].values()]
                )

                csv_output_data.append(
                    [
                        str(example_id),
                        example_question,
                        output_data["base_answer"],
                        output_data["base_answer_duration"],
                        output_data["initial_sub_questions"],
                        output_data["initial_answer"],
                        output_data["initial_answer_duration"],
                        output_data["refined_sub_questions"],
                        output_data["refined_answer"],
                        output_data["refined_answer_duration"],
                        output_data["refined_answer_improves_on_initial_answer"],
                    ]
                )
        except Exception as e:
            logger.error(f"Error processing example {example_id}: {e}")
            failed_example_ids.append(example_id)
            continue


with open(output_file, "w", newline="") as csvfile:
    writer = csv.writer(csvfile, delimiter="\t")
    writer.writerow(
        [
            "example_id",
            "question",
            "base_answer",
            "base_answer_duration",
            "initial_sub_questions",
            "initial_answer",
            "initial_answer_duration",
            "refined_sub_questions",
            "refined_answer",
            "refined_answer_duration",
            "refined_answer_improves_on_initial_answer",
        ]
    )
    writer.writerows(csv_output_data)

print("DONE")
