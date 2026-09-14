#!/usr/bin/env python3
"""Run small, reproducible search experiments beside the craft benchmark services.

Host-side launcher; only Python's standard library and sudo Docker are needed.
Credentials travel from Docker inspect to Docker's stdin in memory, never files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "sha256:d7b4f169c6859611af197f42c358d76935504aaf637fd55231c12e3a8935088d"
DOCKER = ["sudo", "-n", "docker"]
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def select_questions(path: Path, ids: list[str]) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    indexed = {row["question_id"]: row for row in rows}
    if len(indexed) != len(rows) or len(set(ids)) != len(ids):
        raise ValueError("Question IDs must be unique")
    selected = []
    for question_id in ids:
        if not SAFE_ID.fullmatch(question_id) or question_id not in indexed:
            raise ValueError("Question ID is unsafe or absent from the source")
        question = indexed[question_id]["question"]
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 12000
        ):
            raise ValueError(
                "Question must be nonempty text of at most 12000 characters"
            )
        # Gold, expected document IDs, and grading metadata never enter the container.
        selected.append({"question_id": question_id, "question": question})
    return selected


def inspect_runtime() -> tuple[dict, str]:
    if socket.gethostname() != "ip-172-31-7-162.us-west-1.compute.internal":
        raise ValueError("This launcher is restricted to the craft-benchmark host")
    item = json.loads(
        subprocess.check_output(DOCKER + ["inspect", "onyx-harness-v2-api"])
    )[0]
    env = dict(value.split("=", 1) for value in item["Config"]["Env"])
    if (
        item["Image"] != IMAGE
        or not item["State"]["Running"]
        or "onyx_default" not in item["NetworkSettings"]["Networks"]
        or env.get("POSTGRES_DB") != "craft_corpus_v2_20260908"
        or env.get("REDIS_HOST") != "onyx-corpus-v2-cache"
    ):
        raise ValueError(
            "Candidate runtime does not match the verified benchmark identity"
        )
    env.update(
        PYTHONPATH="/app",
        PYTHONDONTWRITEBYTECODE="1",
        ENABLE_CRAFT="false",
        ONYX_V2_APPROVED_TOOLS="",
    )
    # Read only the authorized Braintrust key; never source .env as shell code.
    dotenv = ROOT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            name, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and name.strip() == "BRAINTRUST_API_KEY":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    env["BRAINTRUST_API_KEY"] = value
    if env.get("BRAINTRUST_API_KEY"):
        env["HARNESS_BRAINTRUST_PROJECT_ID"] = "cf1897b4-0bf1-482a-855f-29fca9be0ded"
    if any("\n" in v or "\r" in v for v in env.values()):
        raise ValueError(
            "Multiline environment values cannot be passed via Docker env-file"
        )
    return {
        "image": item["Image"],
        "candidate_container_id": item["Id"],
        "network": "onyx_default",
        "host": socket.gethostname(),
    }, "\n".join(f"{k}={v}" for k, v in env.items()) + "\n"


def launch(
    output: Path,
    env: str,
    mounts: list[str],
    arm: str,
    question: str | None,
    relative_output: str,
    timeout: float,
) -> dict:
    import uuid

    name = "onyx-headless-" + uuid.uuid4().hex[:12]
    command = DOCKER + [
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "onyx_default",
        "--memory",
        "4g",
        "--cpus",
        "2",
        "--log-driver",
        "none",
        "--env-file",
        "/dev/stdin",
        "--entrypoint",
        "python",
        *mounts,
        IMAGE,
        "/app/scripts/headless_harness_worker.py",
        "--config",
        "/experiment/config.json",
        "--arm",
        arm,
        "--output",
        "/experiment/" + relative_output,
    ]
    if question:
        command += ["--question", "/experiment/" + question]
    started = time.monotonic()
    status = "exited"
    try:
        completed = subprocess.run(
            command,
            input=env,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        code = completed.returncode
    except subprocess.TimeoutExpired:
        code = None
        status = "host_timeout"
    finally:
        # Only the uniquely named container created by this call can be removed.
        subprocess.run(
            DOCKER + ["rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    timing = {
        "exit_code": code,
        "status": status,
        "container_wall_ms": (time.monotonic() - started) * 1000,
    }
    write_json(output / relative_output / "container.json", timing)
    return timing


def latency_stats(values: list[float]) -> dict:
    values = sorted(values)

    def percentile(q: float) -> float | None:
        if not values:
            return None
        position = (len(values) - 1) * q
        lo = int(position)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)

    return {
        "sample_count": len(values),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "p99": percentile(0.99),
        "max": max(values) if values else None,
        "mean": statistics.mean(values) if values else None,
    }


def summarize(rows: list[dict]) -> dict:
    report = {}
    for arm in ("baseline", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        report[arm] = {
            "sample_count": len(selected),
            "completed": sum(row["outcome"] == "completed" for row in selected),
            "failures": [
                row["question_id"] for row in selected if row["outcome"] != "completed"
            ],
            **{
                metric: latency_stats(
                    [row[metric] for row in selected if row.get(metric) is not None]
                )
                for metric in ("container_wall_ms", "request_total_ms")
            },
        }
    return {
        "arms": report,
        "attempts": rows,
        "interpretation": "Live direct-Python smoke panel, ungraded. Container timing includes imports and startup; request timing excludes them. Percentiles are descriptive. No retries. Missing request timings are excluded with explicit sample counts; container timings retain failures.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", required=True, help="New experiment directory name; never overwritten"
    )
    parser.add_argument(
        "--source-backend",
        type=Path,
        default=ROOT / "code/backend",
        help="Backend snapshot to overlay for a frozen comparison arm",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=ROOT / "questions/questions_cost_benchmark.jsonl",
    )
    parser.add_argument("--question-ids", default="qst_0001,qst_0002,qst_0003")
    parser.add_argument("--provider", default="OpenAI Default")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument(
        "--user-id",
        help="Existing benchmark user UUID; auto-select only if exactly one active user",
    )
    parser.add_argument(
        "--reasoning-effort", choices=["off", "low", "medium", "high"], default="off"
    )
    parser.add_argument(
        "--policy",
        type=Path,
        help="Optional HarnessPolicy JSON; defaults to 500k cumulative task tokens",
    )
    parser.add_argument(
        "--arms", choices=["both", "baseline", "candidate"], default="both"
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--container-timeout",
        type=float,
        default=300,
        help="Separate host failure cutoff, including startup",
    )
    args = parser.parse_args()
    if not SAFE_ID.fullmatch(args.name) or args.container_timeout <= 0:
        parser.error("Use a safe experiment name and positive container timeout")
    questions = select_questions(args.questions, args.question_ids.split(","))
    backend = args.source_backend.resolve()
    if not (backend / "scripts/headless_harness_worker.py").is_file():
        parser.error("Source backend must contain the headless worker")
    runtime, env = inspect_runtime()
    output = ROOT / "experiments" / args.name
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    hashes = {}
    mounts = ["--mount", f"type=bind,src={output},dst=/experiment"]
    for path in sorted(backend.rglob("*.py")):
        if "tests" in path.relative_to(backend).parts:
            continue
        relative = path.relative_to(backend)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
        mounts += ["--mount", f"type=bind,src={target},dst=/app/{relative},readonly"]
    policy = {"max_total_tokens": 500000}
    if args.policy:
        policy.update(json.loads(args.policy.read_text()))
    config = {
        "provider": args.provider,
        "model": args.model,
        "user_id": args.user_id,
        "reasoning_effort": args.reasoning_effort,
        "policy": policy,
    }
    write_json(output / "config.json", config)
    write_json(
        output / "manifest.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "execution_path": "live_direct_python",
            **runtime,
            "source_sha256": hashes,
            "questions": questions,
            "config": config,
            "container_timeout_seconds": args.container_timeout,
            "container_resources": {"memory_bytes": 4294967296, "cpus": 2},
            "process_lifecycle": "fresh container per arm; cold imports and process-local caches",
            "baseline": "InternalSearchAnswer with synthesis enabled, one objective equal to the question",
            "candidate": "AgentHarness controlling evidence-only InternalSearchAnswer; standard outer decisions",
            "comparison_contract": "Same model, reasoning, corpus, ACL user, filters, and shared factuality/citation requirements. Synthesis ownership, prompt framing, and adaptive search differ by design; this is not an isolated synthesis ablation.",
            "baseline_prompt": "onyx/prompts/harness_v2.py:SEARCH_ANSWER_PROMPT",
            "candidate_prompt": "onyx/prompts/harness_v2.py:AGENT_SYSTEM_PROMPT",
        },
    )
    (output / "preflight").mkdir()
    timing = launch(
        output, env, mounts, "preflight", None, "preflight", args.container_timeout
    )
    if timing["exit_code"] != 0:
        print(f"Preflight failed; inspect {output / 'preflight'}")
        return 1
    identity = json.loads((output / "preflight/preflight.json").read_text())
    config["user_id"] = identity["user_id"]
    write_json(output / "config.json", config)
    print(
        f"Verified isolated database/index and benchmark user. Artifacts: {output}",
        flush=True,
    )
    if args.preflight_only:
        return 0
    rows = []
    for index, question in enumerate(questions):
        qdir = output / question["question_id"]
        qdir.mkdir()
        write_json(qdir / "question.json", question)
        arms = ["baseline", "candidate"] if args.arms == "both" else [args.arms]
        if index % 2:
            arms.reverse()
        for arm in arms:
            relative = f"{question['question_id']}/{arm}"
            (output / relative).mkdir()
            print(f"Running {question['question_id']} {arm}", flush=True)
            timing = launch(
                output,
                env,
                mounts,
                arm,
                f"{question['question_id']}/question.json",
                relative,
                args.container_timeout,
            )
            result_path = output / relative / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            outcome = (
                result.get("outcome", "error")
                if timing["status"] == "exited"
                else timing["status"]
            )
            rows.append(
                {
                    "question_id": question["question_id"],
                    "arm": arm,
                    **timing,
                    "outcome": outcome,
                    "request_total_ms": result.get("request_total_ms"),
                }
            )
            write_json(output / "summary.json", summarize(rows))
            print(
                f"  {outcome}; container {timing['container_wall_ms'] / 1000:.1f}s",
                flush=True,
            )
    return 0 if all(row["outcome"] == "completed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
