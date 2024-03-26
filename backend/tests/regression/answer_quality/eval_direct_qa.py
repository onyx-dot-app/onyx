import argparse
import builtins
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from typing import TextIO

import yaml
from sqlalchemy.orm import Session

from danswer.chat.models import LLMMetricsContainer
from danswer.configs.constants import MessageType
from danswer.db.engine import get_sqlalchemy_engine
from danswer.one_shot_answer.answer_question import get_search_answer
from danswer.one_shot_answer.models import DirectQARequest
from danswer.one_shot_answer.models import ThreadMessage
from danswer.search.models import IndexFilters
from danswer.search.models import OptionalSearchSetting
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import RetrievalDetails
from danswer.search.models import RetrievalMetricsContainer
from danswer.utils.callbacks import MetricsHander


engine = get_sqlalchemy_engine()


@contextmanager
def redirect_print_to_file(file: TextIO) -> Any:
    original_print = builtins.print
    builtins.print = lambda *args, **kwargs: original_print(*args, file=file, **kwargs)
    try:
        yield
    finally:
        builtins.print = original_print


def load_yaml(filepath: str) -> dict:
    with open(filepath, "r") as file:
        data = yaml.safe_load(file)
    return data


def word_wrap(s: str, max_line_size: int = 100, prepend_tab: bool = True) -> str:
    words = s.split()

    current_line: list[str] = []
    result_lines: list[str] = []
    current_length = 0
    for word in words:
        if len(word) > max_line_size:
            if current_line:
                result_lines.append(" ".join(current_line))
                current_line = []
                current_length = 0

            result_lines.append(word)
            continue

        if current_length + len(word) + len(current_line) > max_line_size:
            result_lines.append(" ".join(current_line))
            current_line = []
            current_length = 0

        current_line.append(word)
        current_length += len(word)

    if current_line:
        result_lines.append(" ".join(current_line))

    return "\t" + "\n\t".join(result_lines) if prepend_tab else "\n".join(result_lines)


def get_answer_for_question(
    query: str, db_session: Session
) -> tuple[
    str | None,
    RetrievalMetricsContainer | None,
    RerankMetricsContainer | None,
]:
    filters = IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        access_control_list=None,
    )

    messages = [ThreadMessage(message=query, sender=None, role=MessageType.USER)]

    new_message_request = DirectQARequest(
        messages=messages,
        prompt_id=0,
        persona_id=0,
        retrieval_options=RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=True,
            filters=filters,
            enable_auto_detect_filters=False,
        ),
        chain_of_thought=False,
    )

    retrieval_metrics = MetricsHander[RetrievalMetricsContainer]()
    rerank_metrics = MetricsHander[RerankMetricsContainer]()

    answer = get_search_answer(
        query_req=new_message_request,
        user=None,
        max_document_tokens=None,
        max_history_tokens=None,
        db_session=db_session,
        answer_generation_timeout=100,
        enable_reflexion=False,
        bypass_acl=True,
        retrieval_metrics_callback=retrieval_metrics.record_metric,
        rerank_metrics_callback=rerank_metrics.record_metric,
    )

    return (
        answer.answer,
        retrieval_metrics.metrics,
        rerank_metrics.metrics,
    )


def _print_retrieval_metrics(
    metrics_container: RetrievalMetricsContainer, show_all: bool
) -> None:
    for ind, metric in enumerate(metrics_container.metrics):
        if not show_all and ind >= 10:
            break

        if ind != 0:
            print()  # for spacing purposes
        print(f"\tDocument: {metric.document_id}")
        print(f"\tLink: {metric.first_link or 'NA'}")
        section_start = metric.chunk_content_start.replace("\n", " ")
        print(f"\tSection Start: {section_start}")
        print(f"\tSimilarity Distance Metric: {metric.score}")


def _print_reranking_metrics(
    metrics_container: RerankMetricsContainer, show_all: bool
) -> None:
    # Printing the raw scores as they're more informational than post-norm/boosting
    for ind, metric in enumerate(metrics_container.metrics):
        if not show_all and ind >= 10:
            break

        if ind != 0:
            print()  # for spacing purposes
        print(f"\tDocument: {metric.document_id}")
        print(f"\tLink: {metric.first_link or 'NA'}")
        section_start = metric.chunk_content_start.replace("\n", " ")
        print(f"\tSection Start: {section_start}")
        print(f"\tSimilarity Score: {metrics_container.raw_similarity_scores[ind]}")


def _print_llm_metrics(metrics_container: LLMMetricsContainer) -> None:
    print(f"\tPrompt Tokens: {metrics_container.prompt_tokens}")
    print(f"\tResponse Tokens: {metrics_container.response_tokens}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "regression_yaml",
        type=str,
        help="Path to the Questions YAML file.",
        default="./tests/regression/answer_quality/sample_questions.yaml",
        nargs="?",
    )
    parser.add_argument(
        "--real-time", action="store_true", help="Set to use the real-time flow."
    )
    parser.add_argument(
        "--discard-metrics",
        action="store_true",
        help="Set to not include metrics on search, rerank, and token counts.",
    )
    parser.add_argument(
        "--all-results",
        action="store_true",
        help="Set to not include more than the 10 top sections for search and reranking metrics.",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to the output results file.",
        default="./tests/regression/answer_quality/regression_results.txt",
    )
    args = parser.parse_args()

    questions_data = load_yaml(args.regression_yaml)

    with open(args.output, "w") as outfile:
        with redirect_print_to_file(outfile):
            print("Running Question Answering Flow")
            print(
                "Note that running metrics requires tokenizing all "
                "prompts/returns and slightly slows down inference."
            )
            print(
                "Also note that the text embedding model (bi-encoder) currently used is trained for "
                "relative distances, not absolute distances. Therefore cosine similarity values may all be > 0.5 "
                "even for poor matches"
            )

            with Session(engine, expire_on_commit=False) as db_session:
                for sample in questions_data["questions"]:
                    print(
                        f"Running Test for Question {sample['id']}: {sample['question']}"
                    )

                    start_time = datetime.now()
                    (
                        answer,
                        retrieval_metrics,
                        rerank_metrics,
                    ) = get_answer_for_question(sample["question"], db_session)
                    end_time = datetime.now()

                    print(f"====Duration: {end_time - start_time}====")
                    print(f"Question {sample['id']}:")
                    print(f'\t{sample["question"]}')
                    print("\nApproximate Expected Answer:")
                    print(f'\t{sample["expected_answer"]}')
                    print("\nActual Answer:")
                    print(
                        word_wrap(answer)
                        if answer
                        else "\tFailed, either crashed or refused to answer."
                    )
                    if not args.discard_metrics:
                        print("\nRetrieval Metrics:")
                        if retrieval_metrics is None:
                            print("No Retrieval Metrics Available")
                        else:
                            _print_retrieval_metrics(
                                retrieval_metrics, show_all=args.all_results
                            )

                        print("\nReranking Metrics:")
                        if rerank_metrics is None:
                            print("No Reranking Metrics Available")
                        else:
                            _print_reranking_metrics(
                                rerank_metrics, show_all=args.all_results
                            )

                    print("\n\n", flush=True)
