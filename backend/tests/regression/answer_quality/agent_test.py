import csv
import datetime
import json
import os

import yaml

from onyx.agents.agent_search.deep_search.main.graph_builder import (
    main_graph_builder,
)
from onyx.agents.agent_search.deep_search.main.states import MainInput
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.context.search.models import SearchRequest
from onyx.db.engine import get_session_context_manager
from onyx.llm.factory import get_default_llms


cwd = os.getcwd()
CONFIG = yaml.safe_load(
    open(f"{cwd}/backend/tests/regression/answer_quality/search_test_config.yaml")
)
INPUT_DIR = CONFIG["agent_test_input_folder"]
OUTPUT_DIR = CONFIG["agent_test_output_folder"]


graph = main_graph_builder(test_mode=True)
compiled_graph = graph.compile()
primary_llm, fast_llm = get_default_llms()

# create a local json test data file and use it here


input_file_object = open(
    f"{INPUT_DIR}/agent_test_data.json",
)
output_file = f"{OUTPUT_DIR}/agent_test_output.csv"


test_data = json.load(input_file_object)
example_data = test_data["examples"]
example_ids = test_data["example_ids"]

with get_session_context_manager() as db_session:
    output_data = []

    for example in example_data:
        example_id = example["id"]
        if len(example_ids) > 0 and example_id not in example_ids:
            continue

        example_question = example["question"]
        target_sub_questions = example.get("target_sub_questions", [])
        num_target_sub_questions = len(target_sub_questions)
        search_request = SearchRequest(query=example_question)

        config, search_tool = get_test_config(
            db_session=db_session,
            primary_llm=primary_llm,
            fast_llm=fast_llm,
            search_request=search_request,
        )

        inputs = MainInput()

        start_time = datetime.datetime.now()

        question_result = compiled_graph.invoke(
            input=inputs, config={"metadata": {"config": config}}
        )
        end_time = datetime.datetime.now()

        duration = end_time - start_time
        if num_target_sub_questions > 0:
            chunk_expansion_ratio = (
                question_result["initial_agent_stats"]
                .get("agent_effectiveness", {})
                .get("utilized_chunk_ratio", None)
            )
            support_effectiveness_ratio = (
                question_result["initial_agent_stats"]
                .get("agent_effectiveness", {})
                .get("support_ratio", None)
            )
        else:
            chunk_expansion_ratio = None
            support_effectiveness_ratio = None

        generated_sub_questions = question_result.get("generated_sub_questions", [])
        num_generated_sub_questions = len(generated_sub_questions)
        base_answer = question_result["initial_base_answer"].split("==")[-1]
        agent_answer = question_result["initial_answer"].split("==")[-1]

        output_point = {
            "example_id": example_id,
            "question": example_question,
            "duration": duration,
            "target_sub_questions": target_sub_questions,
            "generated_sub_questions": generated_sub_questions,
            "num_target_sub_questions": num_target_sub_questions,
            "num_generated_sub_questions": num_generated_sub_questions,
            "chunk_expansion_ratio": chunk_expansion_ratio,
            "support_effectiveness_ratio": support_effectiveness_ratio,
            "base_answer": base_answer,
            "agent_answer": agent_answer,
        }

        output_data.append(output_point)


with open(output_file, "w", newline="") as csvfile:
    fieldnames = [
        "example_id",
        "question",
        "duration",
        "target_sub_questions",
        "generated_sub_questions",
        "num_target_sub_questions",
        "num_generated_sub_questions",
        "chunk_expansion_ratio",
        "support_effectiveness_ratio",
        "base_answer",
        "agent_answer",
    ]

    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    writer.writerows(output_data)

print("DONE")
