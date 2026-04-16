from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import TypedDict
from typing import TypeGuard

import aiohttp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


DEFAULT_API_BASE = "http://localhost:3000"
INTERNAL_SEARCH_TOOL_NAME = "internal_search"
INTERNAL_SEARCH_IN_CODE_TOOL_ID = "SearchTool"
MAX_REQUEST_ATTEMPTS = 5
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
QUESTION_TIMEOUT_SECONDS = 300
QUESTION_RETRY_PAUSE_SECONDS = 30
MAX_QUESTION_ATTEMPTS = 3


@dataclass(frozen=True)
class QuestionRecord:
    question_id: str
    question: str


@dataclass(frozen=True)
class AnswerRecord:
    question_id: str
    answer: str
    document_ids: list[str]


@dataclass(frozen=True)
class FailedQuestionRecord:
    question_id: str
    error: str


class Citation(TypedDict, total=False):
    citation_number: int
    document_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Submit questions to Onyx chat with internal search forced and write "
            "answers to a JSONL file."
        )
    )
    parser.add_argument(
        "--questions-file",
        type=Path,
        required=True,
        help="Path to the input questions JSONL file.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Path to the output answers JSONL file.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        required=True,
        help="API key used to authenticate against Onyx.",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default=DEFAULT_API_BASE,
        help=(
            "Frontend base URL for Onyx. If `/api` is omitted, it will be added "
            f"automatically. Default: {DEFAULT_API_BASE}"
        ),
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of questions to process in parallel. Default: 1.",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="Optional cap on how many questions to process. Defaults to all.",
    )
    return parser.parse_args()


def normalize_api_base(api_base: str) -> str:
    normalized = api_base.rstrip("/")
    if normalized.endswith("/api"):
        return normalized
    return f"{normalized}/api"


def load_completed_question_ids(output_file: Path) -> set[str]:
    if not output_file.exists():
        return set()

    completed_ids: set[str] = set()
    with output_file.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            question_id = record.get("question_id")
            if isinstance(question_id, str) and question_id:
                completed_ids.add(question_id)

    return completed_ids


def load_questions(questions_file: Path) -> list[QuestionRecord]:
    if not questions_file.exists():
        raise FileNotFoundError(f"Questions file not found: {questions_file}")

    questions: list[QuestionRecord] = []
    with questions_file.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue

            try:
                payload = json.loads(stripped_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {questions_file}"
                ) from exc

            question_id = payload.get("question_id")
            question = payload.get("question")

            if not isinstance(question_id, str) or not question_id:
                raise ValueError(
                    f"Line {line_number} is missing a non-empty `question_id`."
                )
            if not isinstance(question, str) or not question:
                raise ValueError(
                    f"Line {line_number} is missing a non-empty `question`."
                )

            questions.append(QuestionRecord(question_id=question_id, question=question))

    return questions


async def read_json_response(
    response: aiohttp.ClientResponse,
) -> dict[str, Any] | list[dict[str, Any]]:
    response_text = await response.text()
    if response.status >= 400:
        raise RuntimeError(
            f"Request to {response.url} failed with {response.status}: {response_text}"
        )

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Request to {response.url} returned non-JSON content: {response_text}"
        ) from exc

    if not isinstance(payload, (dict, list)):
        raise RuntimeError(
            f"Unexpected response payload type from {response.url}: {type(payload)}"
        )

    return payload


async def request_json_with_retries(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    backoff_seconds = 1.0

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=json_payload,
            ) as response:
                if (
                    response.status in RETRIABLE_STATUS_CODES
                    and attempt < MAX_REQUEST_ATTEMPTS
                ):
                    response_text = await response.text()
                    logger.warning(
                        "Retryable response from %s on attempt %s/%s: %s %s",
                        url,
                        attempt,
                        MAX_REQUEST_ATTEMPTS,
                        response.status,
                        response_text,
                    )
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue

                return await read_json_response(response)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if attempt == MAX_REQUEST_ATTEMPTS:
                raise RuntimeError(
                    f"Request to {url} failed after {MAX_REQUEST_ATTEMPTS} attempts."
                ) from exc

            logger.warning(
                "Request to %s failed on attempt %s/%s: %s",
                url,
                attempt,
                MAX_REQUEST_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(backoff_seconds)
            backoff_seconds *= 2

    raise RuntimeError(f"Request to {url} failed unexpectedly.")


def extract_document_ids(citation_info: object) -> list[str]:
    if not isinstance(citation_info, list):
        return []

    sorted_citations = sorted(
        (citation for citation in citation_info if _is_valid_citation(citation)),
        key=_citation_sort_key,
    )

    document_ids: list[str] = []
    seen_document_ids: set[str] = set()
    for citation in sorted_citations:
        document_id = citation["document_id"]
        if document_id not in seen_document_ids:
            seen_document_ids.add(document_id)
            document_ids.append(document_id)

    return document_ids


def _is_valid_citation(citation: object) -> TypeGuard[Citation]:
    return (
        isinstance(citation, dict)
        and isinstance(
            citation.get("document_id"), str  # ty: ignore[invalid-argument-type]
        )
        and bool(citation["document_id"])  # ty: ignore[invalid-argument-type]
    )


def _citation_sort_key(citation: Citation) -> int:
    citation_number = citation.get("citation_number")
    if isinstance(citation_number, int):
        return citation_number
    return sys.maxsize


async def fetch_internal_search_tool_id(
    session: aiohttp.ClientSession,
    api_base: str,
    headers: dict[str, str],
) -> int:
    payload = await request_json_with_retries(
        session=session,
        method="GET",
        url=f"{api_base}/tool",
        headers=headers,
    )

    if not isinstance(payload, list):
        raise RuntimeError("Expected `/tool` to return a list.")

    for tool in payload:
        if not isinstance(tool, dict):
            continue

        if tool.get("in_code_tool_id") == INTERNAL_SEARCH_IN_CODE_TOOL_ID:
            tool_id = tool.get("id")
            if isinstance(tool_id, int):
                return tool_id

    for tool in payload:
        if not isinstance(tool, dict):
            continue

        if tool.get("name") == INTERNAL_SEARCH_TOOL_NAME:
            tool_id = tool.get("id")
            if isinstance(tool_id, int):
                return tool_id

    raise RuntimeError(
        "Could not find the internal search tool in `/tool`. "
        "Make sure SearchTool is available for this environment."
    )


async def submit_question(
    session: aiohttp.ClientSession,
    api_base: str,
    headers: dict[str, str],
    internal_search_tool_id: int,
    question_record: QuestionRecord,
) -> AnswerRecord:
    payload = {
        "message": question_record.question,
        "chat_session_info": {"persona_id": 0},
        "parent_message_id": None,
        "file_descriptors": [],
        "allowed_tool_ids": [internal_search_tool_id],
        "forced_tool_id": internal_search_tool_id,
        "stream": False,
    }

    response_payload = await request_json_with_retries(
        session=session,
        method="POST",
        url=f"{api_base}/chat/send-chat-message",
        headers=headers,
        json_payload=payload,
    )

    if not isinstance(response_payload, dict):
        raise RuntimeError(
            "Expected `/chat/send-chat-message` to return an object when `stream=false`."
        )

    answer = response_payload.get("answer_citationless")
    if not isinstance(answer, str):
        answer = response_payload.get("answer")

    if not isinstance(answer, str):
        raise RuntimeError(
            f"Response for question {question_record.question_id} is missing `answer`."
        )

    return AnswerRecord(
        question_id=question_record.question_id,
        answer=answer,
        document_ids=extract_document_ids(response_payload.get("citation_info")),
    )


async def generate_answers(
    questions: list[QuestionRecord],
    output_file: Path,
    api_base: str,
    api_key: str,
    parallelism: int,
    skipped: int,
) -> None:
    if parallelism < 1:
        raise ValueError("`--parallelism` must be at least 1.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=30,
        sock_connect=30,
        sock_read=600,
    )
    connector = aiohttp.TCPConnector(limit=parallelism)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("a", encoding="utf-8") as file:
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector
        ) as session:
            internal_search_tool_id = await fetch_internal_search_tool_id(
                session=session,
                api_base=api_base,
                headers=headers,
            )
            logger.info("Using internal search tool id %s", internal_search_tool_id)

            semaphore = asyncio.Semaphore(parallelism)
            progress_lock = asyncio.Lock()
            write_lock = asyncio.Lock()
            completed = 0
            successful = 0
            stuck_count = 0
            failed_questions: list[FailedQuestionRecord] = []
            remaining_count = len(questions)
            overall_total = remaining_count + skipped
            question_durations: list[float] = []
            run_start_time = time.monotonic()

            def print_progress() -> None:
                avg_time = (
                    sum(question_durations) / len(question_durations)
                    if question_durations
                    else 0.0
                )
                elapsed = time.monotonic() - run_start_time
                eta = avg_time * (remaining_count - completed) / max(parallelism, 1)

                done = skipped + completed
                bar_width = 30
                filled = (
                    int(bar_width * done / overall_total)
                    if overall_total
                    else bar_width
                )
                bar = "█" * filled + "░" * (bar_width - filled)
                pct = (done / overall_total * 100) if overall_total else 100.0

                parts = (
                    f"\r{bar} {pct:5.1f}% "
                    f"[{done}/{overall_total}] "
                    f"avg {avg_time:.1f}s/q "
                    f"elapsed {elapsed:.0f}s "
                    f"ETA {eta:.0f}s "
                    f"(ok:{successful} fail:{len(failed_questions)}"
                )
                if stuck_count:
                    parts += f" stuck:{stuck_count}"
                if skipped:
                    parts += f" skip:{skipped}"
                parts += ")"

                sys.stderr.write(parts)
                sys.stderr.flush()

            print_progress()

            async def process_question(question_record: QuestionRecord) -> None:
                nonlocal completed
                nonlocal successful
                nonlocal stuck_count

                last_error: Exception | None = None
                for attempt in range(1, MAX_QUESTION_ATTEMPTS + 1):
                    q_start = time.monotonic()
                    try:
                        async with semaphore:
                            result = await asyncio.wait_for(
                                submit_question(
                                    session=session,
                                    api_base=api_base,
                                    headers=headers,
                                    internal_search_tool_id=internal_search_tool_id,
                                    question_record=question_record,
                                ),
                                timeout=QUESTION_TIMEOUT_SECONDS,
                            )
                    except asyncio.TimeoutError:
                        async with progress_lock:
                            stuck_count += 1
                            logger.warning(
                                "Question %s timed out after %ss (attempt %s/%s, "
                                "total stuck: %s) — retrying in %ss",
                                question_record.question_id,
                                QUESTION_TIMEOUT_SECONDS,
                                attempt,
                                MAX_QUESTION_ATTEMPTS,
                                stuck_count,
                                QUESTION_RETRY_PAUSE_SECONDS,
                            )
                            print_progress()
                        last_error = TimeoutError(
                            f"Timed out after {QUESTION_TIMEOUT_SECONDS}s "
                            f"on attempt {attempt}/{MAX_QUESTION_ATTEMPTS}"
                        )
                        await asyncio.sleep(QUESTION_RETRY_PAUSE_SECONDS)
                        continue
                    except Exception as exc:
                        duration = time.monotonic() - q_start
                        async with progress_lock:
                            completed += 1
                            question_durations.append(duration)
                            failed_questions.append(
                                FailedQuestionRecord(
                                    question_id=question_record.question_id,
                                    error=str(exc),
                                )
                            )
                            logger.exception(
                                "Failed question %s (%s/%s)",
                                question_record.question_id,
                                completed,
                                remaining_count,
                            )
                            print_progress()
                        return

                    duration = time.monotonic() - q_start

                    async with write_lock:
                        file.write(json.dumps(asdict(result), ensure_ascii=False))
                        file.write("\n")
                        file.flush()

                    async with progress_lock:
                        completed += 1
                        successful += 1
                        question_durations.append(duration)
                        print_progress()
                    return

                # All attempts exhausted due to timeouts
                async with progress_lock:
                    completed += 1
                    failed_questions.append(
                        FailedQuestionRecord(
                            question_id=question_record.question_id,
                            error=str(last_error),
                        )
                    )
                    logger.error(
                        "Question %s failed after %s timeout attempts (%s/%s)",
                        question_record.question_id,
                        MAX_QUESTION_ATTEMPTS,
                        completed,
                        remaining_count,
                    )
                    print_progress()

            await asyncio.gather(
                *(process_question(question_record) for question_record in questions)
            )

            # Final newline after progress bar
            sys.stderr.write("\n")
            sys.stderr.flush()

            total_elapsed = time.monotonic() - run_start_time
            avg_time = (
                sum(question_durations) / len(question_durations)
                if question_durations
                else 0.0
            )
            stuck_suffix = f", {stuck_count} stuck timeouts" if stuck_count else ""
            resume_suffix = (
                f" — {skipped} previously completed, "
                f"{skipped + successful}/{overall_total} overall"
                if skipped
                else ""
            )
            logger.info(
                "Done: %s/%s successful in %.1fs (avg %.1fs/question%s)%s",
                successful,
                remaining_count,
                total_elapsed,
                avg_time,
                stuck_suffix,
                resume_suffix,
            )

            if failed_questions:
                logger.warning(
                    "%s questions failed:",
                    len(failed_questions),
                )
                for failed_question in failed_questions:
                    logger.warning(
                        "Failed question %s: %s",
                        failed_question.question_id,
                        failed_question.error,
                    )


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions_file)
    api_base = normalize_api_base(args.api_base)

    if args.max_questions is not None:
        if args.max_questions < 1:
            raise ValueError("`--max-questions` must be at least 1 when provided.")
        questions = questions[: args.max_questions]

    completed_ids = load_completed_question_ids(args.output_file)
    logger.info(
        "Found %s already-answered question IDs in %s",
        len(completed_ids),
        args.output_file,
    )
    total_before_filter = len(questions)
    questions = [q for q in questions if q.question_id not in completed_ids]
    skipped = total_before_filter - len(questions)

    if skipped:
        logger.info(
            "Resuming: %s/%s already answered, %s remaining",
            skipped,
            total_before_filter,
            len(questions),
        )
    else:
        logger.info("Loaded %s questions from %s", len(questions), args.questions_file)

    if not questions:
        logger.info("All questions already answered. Nothing to do.")
        return

    logger.info("Writing answers to %s", args.output_file)

    asyncio.run(
        generate_answers(
            questions=questions,
            output_file=args.output_file,
            api_base=api_base,
            api_key=args.api_key,
            parallelism=args.parallelism,
            skipped=skipped,
        )
    )


if __name__ == "__main__":
    main()
