import argparse
import json

from sqlalchemy.orm import Session

from danswer.configs.constants import MessageType
from danswer.db.engine import get_sqlalchemy_engine
from danswer.one_shot_answer.answer_question import get_search_answer
from danswer.one_shot_answer.models import DirectQARequest
from danswer.one_shot_answer.models import OneShotQAResponse
from danswer.one_shot_answer.models import ThreadMessage
from danswer.search.models import IndexFilters
from danswer.search.models import OptionalSearchSetting
from danswer.search.models import RetrievalDetails


def get_answer_for_question(query: str, db_session: Session) -> OneShotQAResponse:
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
        return_contexts=True,
    )

    answer = get_search_answer(
        query_req=new_message_request,
        user=None,
        max_document_tokens=None,
        max_history_tokens=None,
        db_session=db_session,
        answer_generation_timeout=100,
        enable_reflexion=False,
        bypass_acl=True,
    )

    return answer


def read_questions(questions_file_path: str) -> list[dict]:
    samples = []
    with open(questions_file_path, "r", encoding="utf-8") as file:
        for line in file:
            sample = json.loads(line.strip())
            samples.append(sample)
    return samples


def get_relari_outputs(samples: list[dict]) -> list[dict]:
    relari_outputs = []
    with Session(get_sqlalchemy_engine(), expire_on_commit=False) as db_session:
        for sample in samples:
            answer = get_answer_for_question(
                query=sample["question"], db_session=db_session
            )
            assert answer.contexts

            relari_outputs.append(
                {
                    "label": sample["uid"],
                    "question": sample["question"],
                    "answer": answer.answer,
                    "retrieved_context": [
                        context.content for context in answer.contexts.contexts
                    ],
                }
            )

    return relari_outputs


def write_output_file(relari_outputs: list[dict], output_file: str) -> None:
    with open(output_file, "w", encoding="utf-8") as file:
        for output in relari_outputs:
            file.write(json.dumps(output) + "\n")


def main(questions_file: str, output_file: str, limit: int | None = None) -> None:
    samples = read_questions(questions_file)

    if limit is not None:
        samples = samples[:limit]

    # Use to be in this format but has since changed
    # response_dict = {
    #     "question": sample["question"],
    #     "retrieved_contexts": [
    #         context.content for context in answer.contexts.contexts
    #     ],
    #     "ground_truth_contexts": sample["ground_truth_contexts"],
    #     "answer": answer.answer,
    #     "ground_truths": sample["ground_truths"],
    # }

    relari_outputs = get_relari_outputs(samples=samples)

    write_output_file(relari_outputs, output_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--questions_file",
        type=str,
        help="Path to the Relari questions file.",
        default="./tests/regression/answer_quality/combined_golden_dataset.jsonl",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        help="Path to the output results file.",
        default="./tests/regression/answer_quality/relari_results.txt",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of examples to process.",
    )
    args = parser.parse_args()

    main(args.questions_file, args.output_file, args.limit)
