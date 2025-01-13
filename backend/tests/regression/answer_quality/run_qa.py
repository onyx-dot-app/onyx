import json
import multiprocessing
import os
import shutil
import time

import yaml

from tests.regression.answer_quality.api_utils import get_answer_from_query
from tests.regression.answer_quality.cli_utils import get_current_commit_sha
from tests.regression.answer_quality.cli_utils import get_docker_container_env_vars

RESULTS_FILENAME = "results.jsonl"
METADATA_FILENAME = "metadata.yaml"


def _populate_results_file(output_folder_path: str, all_qa_output: list[dict]) -> None:
    output_file_path = os.path.join(output_folder_path, RESULTS_FILENAME)
    with open(output_file_path, "a", encoding="utf-8") as file:
        for qa_output in all_qa_output:
            file.write(json.dumps(qa_output) + "\n")
            file.flush()


def _update_metadata_file(test_output_folder: str, invalid_answer_count: int) -> None:
    metadata_path = os.path.join(test_output_folder, METADATA_FILENAME)
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = yaml.safe_load(file)

    metadata["number_of_failed_questions"] = invalid_answer_count
    with open(metadata_path, "w", encoding="utf-8") as yaml_file:
        yaml.dump(metadata, yaml_file)


def _read_questions_jsonl(questions_file_path: str) -> list[dict]:
    questions = []
    with open(questions_file_path, "r") as file:
        for line in file:
            json_obj = json.loads(line)
            questions.append(json_obj)
    return questions


def _get_test_output_folder(config: dict) -> str:
    base_output_folder = os.path.expanduser(config["output_folder"])
    if config["env_name"]:
        base_output_folder = os.path.join(
            base_output_folder, config["env_name"], "evaluations_output"
        )
    else:
        base_output_folder = os.path.join(base_output_folder, "no_defined_env_name")

    counter = 1
    output_folder_path = os.path.join(base_output_folder, "run_1")
    while os.path.exists(output_folder_path):
        output_folder_path = os.path.join(
            output_folder_path.replace(f"run_{counter-1}", f"run_{counter}"),
        )
        counter += 1

    os.makedirs(output_folder_path, exist_ok=True)

    return output_folder_path


def _initialize_files(config: dict) -> tuple[str, list[dict]]:
    test_output_folder = _get_test_output_folder(config)

    questions_file_path = config["questions_file"]

    questions = _read_questions_jsonl(questions_file_path)

    metadata = {
        "commit_sha": get_current_commit_sha(),
        "env_name": config["env_name"],
        "test_config": config,
        "number_of_questions_in_dataset": len(questions),
    }

    if config["env_name"]:
        env_vars = get_docker_container_env_vars(config["env_name"])
        if env_vars["ENV_SEED_CONFIGURATION"]:
            del env_vars["ENV_SEED_CONFIGURATION"]
        if env_vars["GPG_KEY"]:
            del env_vars["GPG_KEY"]
        if metadata["test_config"]["llm"]["api_key"]:
            del metadata["test_config"]["llm"]["api_key"]
        metadata.update(env_vars)
    metadata_path = os.path.join(test_output_folder, METADATA_FILENAME)
    print("saving metadata to:", metadata_path)
    with open(metadata_path, "w", encoding="utf-8") as yaml_file:
        yaml.dump(metadata, yaml_file)

    copied_questions_file_path = os.path.join(
        test_output_folder, os.path.basename(questions_file_path)
    )
    shutil.copy2(questions_file_path, copied_questions_file_path)

    if config["zipped_documents_file"]:
        zipped_files_path = config["zipped_documents_file"]
        copied_zipped_documents_path = os.path.join(
            test_output_folder, os.path.basename(zipped_files_path)
        )
        shutil.copy2(zipped_files_path, copied_zipped_documents_path)

        zipped_files_folder = os.path.dirname(zipped_files_path)
        jsonl_file_path = os.path.join(zipped_files_folder, "target_docs.jsonl")
        if os.path.exists(jsonl_file_path):
            copied_jsonl_path = os.path.join(test_output_folder, "target_docs.jsonl")
            shutil.copy2(jsonl_file_path, copied_jsonl_path)

    return test_output_folder, questions


def _process_question(question_data: dict, config: dict, question_number: int) -> dict:
    query = question_data["question"]
    context_data_list, answer = get_answer_from_query(
        query=query,
        only_retrieve_docs=config["only_retrieve_docs"],
        env_name=config["env_name"],
    )
    print(f"On question number {question_number}")
    print(f"query: {query}")

    if not context_data_list:
        print("No answer or context found")
    else:
        print(f"answer: {answer[:50]}...")
        print(f"{len(context_data_list)} context docs found")
    print("\n")

    output = {
        "question_data": question_data,
        "answer": answer,
        "context_data_list": context_data_list,
    }

    return output


def _process_and_write_query_results(config: dict) -> None:
    start_time = time.time()
    test_output_folder, questions = _initialize_files(config)
    print("saving test results to folder:", test_output_folder)

    if config["limit"] is not None:
        questions = questions[: config["limit"]]

    # Use multiprocessing to process questions
    with multiprocessing.Pool() as pool:
        results = pool.starmap(
            _process_question,
            [(question, config, i + 1) for i, question in enumerate(questions)],
        )

    _populate_results_file(test_output_folder, results)

    invalid_answer_count = 0
    for result in results:
        if len(result["context_data_list"]) == 0:
            invalid_answer_count += 1

    _update_metadata_file(test_output_folder, invalid_answer_count)

    if invalid_answer_count:
        print(f"Warning: {invalid_answer_count} questions failed!")
        print("Suggest restarting the vespa container and rerunning")

    time_to_finish = time.time() - start_time
    minutes, seconds = divmod(int(time_to_finish), 60)
    print(
        f"Took {minutes:02d}:{seconds:02d} to ask and answer {len(results)} questions"
    )
    print("saved test results to folder:", test_output_folder)


def run_qa_test_and_save_results(env_name: str = "") -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "search_test_config.yaml")
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise TypeError("config must be a dictionary")

    if not env_name:
        env_name = config["environment_name"]

    config["env_name"] = env_name
    _process_and_write_query_results(config)


if __name__ == "__main__":
    """
    To run a different set of questions, update the questions_file in search_test_config.yaml
    If there is more than one instance of Onyx running, specify the env_name in search_test_config.yaml
    """
    run_qa_test_and_save_results()
