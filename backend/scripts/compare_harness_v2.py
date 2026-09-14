"""Small, explicit A/B client. Writes raw results; never retries failed answers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests


def checked_json(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Expected an object response")
    return payload


def run_legacy(
    session: requests.Session, api: str, question: str, args: argparse.Namespace
) -> dict[str, Any]:
    started = time.monotonic()
    created = checked_json(
        session.post(
            api + "/chat/create-chat-session",
            json={"persona_id": args.persona_id},
            timeout=30,
        )
    )
    session_id = created["chat_session_id"]
    response = session.put(
        api + "/chat/update-chat-session-reasoning",
        json={
            "chat_session_id": session_id,
            "reasoning_effort_override": args.reasoning_effort,
        },
        timeout=30,
    )
    response.raise_for_status()
    setup_ms = (time.monotonic() - started) * 1000
    body: dict[str, Any] = {
        "chat_session_id": session_id,
        "message": question,
        "parent_message_id": None,
        "stream": False,
        "llm_override": {"model_provider": args.provider, "model_version": args.model},
    }
    if args.legacy_tool_id is not None:
        body["allowed_tool_ids"] = [args.legacy_tool_id]
    result = checked_json(
        session.post(api + "/chat/send-chat-message", json=body, timeout=args.timeout)
    )
    return {
        "raw": result,
        "answer": result.get("answer", ""),
        "outcome": "blocked" if result.get("error_msg") else "completed",
        "setup_ms": setup_ms,
        "chat_session_id": session_id,
    }


def run_v2(
    session: requests.Session, api: str, question: str, args: argparse.Namespace
) -> dict[str, Any]:
    speed_options: dict[str, Any] = {}
    if args.concise_answers:
        speed_options["concise_answers"] = True
    if args.completion_mode != "standard":
        speed_options["completion_mode"] = args.completion_mode
    result = checked_json(
        session.post(
            api + "/harness/v2/run",
            json={
                "question": question,
                "persona_id": args.persona_id,
                "provider": args.provider,
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "policy": json.loads(args.policy_json),
                "include_persona_tools": args.include_persona_tools,
                **speed_options,
            },
            timeout=args.timeout,
        )
    )
    return {
        "raw": result,
        "answer": result["result"]["answer"],
        "outcome": result["result"]["outcome"],
        "setup_ms": result["setup_ms"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-prefix", default="/api")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--persona-id", type=int, default=0)
    parser.add_argument(
        "--reasoning-effort", choices=["low", "medium", "high"], default="low"
    )
    parser.add_argument("--variant", choices=["legacy", "v2", "both"], default="both")
    parser.add_argument("--legacy-tool-id", type=int)
    parser.add_argument("--include-persona-tools", action="store_true")
    parser.add_argument("--concise-answers", action="store_true")
    parser.add_argument(
        "--completion-mode", choices=["standard", "minimal"], default="standard"
    )
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--policy-json", default="{}")
    args = parser.parse_args()
    if args.limit < 1 or args.timeout <= 0:
        parser.error("Limit and timeout must be positive")
    password = os.environ.get("ONYX_BENCH_PASSWORD")
    if not password:
        parser.error("Set ONYX_BENCH_PASSWORD in the environment")
    email = os.environ.get("ONYX_BENCH_EMAIL", "roshan@onyx.app")
    policy = json.loads(args.policy_json)
    if not isinstance(policy, dict):
        parser.error("policy-json must be an object")
    questions = [
        json.loads(line)
        for line in args.questions.read_text().splitlines()
        if line.strip()
    ][: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    api = args.base_url.rstrip("/") + "/" + args.api_prefix.strip("/")
    manifest = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    manifest.update(
        {
            "question_file_sha256": hashlib.sha256(
                args.questions.read_bytes()
            ).hexdigest(),
            "comparison_scope": "End-to-end variants; tool/answer policies differ. Not an isolated causal estimate.",
            "retries": 0,
            "concurrency": 1,
            "streaming": False,
        }
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    with requests.Session() as session:
        session.post(
            api + "/auth/login",
            data={"username": email, "password": password},
            timeout=30,
        ).raise_for_status()
        with (args.output_dir / "results.jsonl").open("x") as stream:
            for index, row in enumerate(questions):
                variants = (
                    ["legacy", "v2"] if args.variant == "both" else [args.variant]
                )
                if args.variant == "both" and index % 2:
                    variants.reverse()
                for variant in variants:
                    started = time.monotonic()
                    result: dict[str, Any] = {
                        "question_id": row["question_id"],
                        "question": row["question"],
                        "variant": variant,
                    }
                    try:
                        result.update(
                            (run_legacy if variant == "legacy" else run_v2)(
                                session, api, row["question"], args
                            )
                        )
                    except (requests.RequestException, ValueError, KeyError) as exc:
                        result.update(
                            outcome="transport_error",
                            error_type=type(exc).__name__,
                            answer="",
                        )
                    result["client_total_ms"] = (time.monotonic() - started) * 1000
                    stream.write(json.dumps(result) + "\n")
                    stream.flush()
                    print(
                        row["question_id"],
                        variant,
                        result["outcome"],
                        round(result["client_total_ms"]),
                    )


if __name__ == "__main__":
    main()
