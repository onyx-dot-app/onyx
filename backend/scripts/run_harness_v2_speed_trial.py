"""Run a bounded v2 speed trial with fixed comparable settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_ARMS: dict[str, dict[str, Any]] = {
    "control": {"concise_answers": False, "completion_mode": "standard"},
    "optimized": {"concise_answers": True, "completion_mode": "minimal"},
}
DEFAULT_POLICY: dict[str, Any] = {"max_total_tokens": 500000}
SAFE_ARM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
RESERVED_ARM_KEYS = {
    "auth",
    "email",
    "include_persona_tools",
    "model",
    "password",
    "persona",
    "persona_id",
    "provider",
    "question",
    "reasoning_effort",
    "username",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_questions(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def select_questions(
    rows: list[dict[str, Any]], question_ids: str | None
) -> tuple[list[str], list[dict[str, str]]]:
    indexed = {r["question_id"]: r for r in rows}
    ids = question_ids.split(",") if question_ids else [r["question_id"] for r in rows]
    if (
        len(indexed) != len(rows)
        or len(set(ids)) != len(ids)
        or not set(ids) <= set(indexed)
    ):
        raise ValueError("Question IDs must be unique and present in the source")
    return ids, [{k: indexed[q][k] for k in ("question_id", "question")} for q in ids]


def load_arms(path: Path | None) -> dict[str, dict[str, Any]]:
    arms = DEFAULT_ARMS if path is None else json.loads(path.read_text())
    if not isinstance(arms, dict) or len(arms) < 2:
        raise ValueError("Arms file must contain at least two named arms")

    validated: dict[str, dict[str, Any]] = {}
    for name, options in arms.items():
        if not isinstance(name, str) or not SAFE_ARM_NAME.fullmatch(name):
            raise ValueError(f"Unsafe arm name: {name!r}")
        if not isinstance(options, dict):
            raise ValueError(f"Arm {name} must map to a request option object")
        reserved = RESERVED_ARM_KEYS & set(options)
        if reserved:
            blocked = ", ".join(sorted(reserved))
            raise ValueError(
                f"Arm {name} cannot override fixed request keys: {blocked}"
            )
        policy = options.get("policy")
        if policy is not None and not isinstance(policy, dict):
            raise ValueError(f"Arm {name} policy must be an object")
        validated[name] = dict(options)
    return validated


def rotated_order(arms: dict[str, dict[str, Any]], question_index: int) -> list[str]:
    names = list(arms)
    split = question_index % len(names)
    return names[split:] + names[:split]


def request_payload(
    *,
    question: str,
    provider: str,
    model: str,
    arm_options: dict[str, Any],
) -> dict[str, Any]:
    options = dict(arm_options)
    policy = {**DEFAULT_POLICY, **options.pop("policy", {})}
    return {
        "question": question,
        "persona_id": 0,
        "provider": provider,
        "model": model,
        "reasoning_effort": "low",
        "include_persona_tools": False,
        "policy": policy,
        **options,
    }


def authenticate(
    session: requests.Session,
    api: str,
    email: str,
    password: str,
) -> None:
    session.post(
        api + "/auth/login",
        data={"username": email, "password": password},
        timeout=30,
    ).raise_for_status()


def run_arm(
    *,
    session: requests.Session,
    api: str,
    question: dict[str, str],
    arm: str,
    arm_options: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        **question,
        "variant": "v2",
        "arm": arm,
        "started_at": utc_now(),
    }
    started = time.monotonic()
    try:
        response = session.post(
            api + "/harness/v2/run",
            json=request_payload(
                question=question["question"],
                provider=provider,
                model=model,
                arm_options=arm_options,
            ),
            timeout=180,
        )
        response.raise_for_status()
        raw = response.json()
        row.update(
            raw=raw,
            answer=raw["result"]["answer"],
            outcome=raw["result"]["outcome"],
            setup_ms=raw["setup_ms"],
        )
    except (requests.RequestException, ValueError, KeyError) as exc:
        row.update(
            outcome="transport_error",
            answer="",
            error_type=type(exc).__name__,
        )
    row["client_total_ms"] = (time.monotonic() - started) * 1000
    return row


def run_question_group(
    *,
    api: str,
    email: str,
    password: str,
    question: dict[str, str],
    question_index: int,
    arms: dict[str, dict[str, Any]],
    provider: str,
    model: str,
) -> list[dict[str, Any]]:
    with requests.Session() as session:
        try:
            authenticate(session, api, email, password)
        except requests.RequestException as exc:
            return [
                {
                    **question,
                    "variant": "v2",
                    "arm": arm,
                    "started_at": utc_now(),
                    "outcome": "transport_error",
                    "answer": "",
                    "error_type": type(exc).__name__,
                    "client_total_ms": 0,
                }
                for arm in rotated_order(arms, question_index)
            ]
        return [
            run_arm(
                session=session,
                api=api,
                question=question,
                arm=arm,
                arm_options=arms[arm],
                provider=provider,
                model=model,
            )
            for arm in rotated_order(arms, question_index)
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-prefix", default="/api/harness-v2")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--question-ids")
    parser.add_argument("--arms-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", default="OpenAI Default")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 3:
        parser.error("--concurrency must be between 1 and 3")
    password = os.environ.get("ONYX_BENCH_PASSWORD")
    if not password:
        parser.error("Set ONYX_BENCH_PASSWORD")
    try:
        rows = read_questions(args.questions)
        ids, questions = select_questions(rows, args.question_ids)
        arms = load_arms(args.arms_file)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        parser.error(str(exc))
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {
        "image_digest": args.image_digest,
        "model": args.model,
        "provider": args.provider,
        "reasoning_effort": "low",
        "arms": arms,
        "policy": DEFAULT_POLICY,
        "question_ids": ids,
        "questions_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "concurrency": args.concurrency,
        "retries": 0,
        "started_at": utc_now(),
        "comparison": (
            "Custom arms from arms file."
            if args.arms_file
            else "Combined brevity and minimal/compact completion treatment; not individual causal attribution."
        ),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    api = args.base_url.rstrip("/") + "/" + args.api_prefix.strip("/")
    email = os.environ.get("ONYX_BENCH_EMAIL", "roshan@onyx.app")
    streams = {arm: (args.output / f"results_{arm}.jsonl").open("x") for arm in arms}
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(
                    run_question_group,
                    api=api,
                    email=email,
                    password=password,
                    question=question,
                    question_index=index,
                    arms=arms,
                    provider=args.provider,
                    model=args.model,
                ): index
                for index, question in enumerate(questions)
            }
            completed: dict[int, list[dict[str, Any]]] = {}
            next_index = 0
            for future in as_completed(futures):
                completed[futures[future]] = future.result()
                while next_index in completed:
                    # Keep output files in question order even when groups finish out of order.
                    for row in completed.pop(next_index):
                        streams[row["arm"]].write(json.dumps(row) + "\n")
                        streams[row["arm"]].flush()
                        print(
                            row["question_id"],
                            row["arm"],
                            row["outcome"],
                            round(row["client_total_ms"]),
                            flush=True,
                        )
                    next_index += 1
    finally:
        for stream in streams.values():
            stream.close()


if __name__ == "__main__":
    main()
