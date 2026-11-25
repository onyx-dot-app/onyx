"""Benchmark of one chat turn: time to first token and the work behind it.

Starts a real API server on a throwaway database and a mock LLM, sends chat
turns over HTTP, and reports where the time before the first answer token
goes, the CPU of the server per turn, and the SQL statements, commits, cache
commands and threads per turn. It then checks the stream, the LLM request and
the saved turn against a set of gates. The exit status is 1 when a gate fails.

Usage:
    cd backend && uv run python -m scripts.benchmark_chat_turn \
        [--scenarios warm,new-session,long-history] [--turns 30] \
        [--update-golden] [--json-out report.json]

Everything it creates has the prefix `chat_bench`: a Postgres database, an
OpenSearch index name and a Redis database of its own.
See scripts/chat_bench/README.md.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import psutil
from pydantic import BaseModel

from scripts.benchmark_docprocessing import _LOCK_PATH, _free_port, _read_env_file

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR.parent / ".vscode" / ".env"
_GOLDEN_PATH = Path(__file__).resolve().parent / "chat_bench" / "golden.json"
_BENCH_PREFIX = "chat_bench"
_SCRIPT_ID = "bench"
_MODEL_NAME = "mock-model"
_EMAIL = "chat_bench@example.com"
_PASSWORD = "ChatBenchPassword123!"

# No "[": the citation processor holds back text that can start a citation.
_ANSWER = (
    "The benchmark answer is a fixed text. It has several sentences, so the "
    "stream holds more than one chunk. Each run returns the same words in the "
    "same order, and the gates compare them with the saved message."
)
_QUESTION = "What is the status of the quarterly migration project?"

_SCENARIOS = ("warm", "new-session", "long-history")
_LONG_HISTORY_TURNS = 40
_WARM_UP_TURNS = 3

# Parts of the LLM request that change between runs with no change in content.
_VOLATILE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?( ?[AP]M)?\b"),
    re.compile(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),? "
        r"(January|February|March|April|May|June|July|August|September|October|"
        r"November|December) \d{1,2},? \d{4}\b"
    ),
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|"
        r"November|December) \d{1,2},? \d{4}\b"
    ),
)


class TurnResult(BaseModel):
    session_id: str
    line_kinds: list[str]
    answer: str
    errors: list[str]
    stops: int
    llm_requests: int
    request_digest: str | None
    transcript_digest: str
    reserved_assistant_message_id: int | None
    # Milliseconds from the moment the client sent the request.
    headers_ms: float
    first_line_ms: float
    first_token_ms: float | None
    stop_ms: float | None
    close_ms: float
    # Split of first_token_ms. None when the mock saw no request.
    pre_llm_ms: float | None
    llm_ms: float | None
    post_llm_ms: float | None


class Gates:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append({"gate": name, "passed": passed, "detail": detail})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [r for r in self.results if not r["passed"]]


def _bench_env(mock_url: str, log_level: str) -> dict[str, str]:
    env = _read_env_file(_ENV_FILE)
    env.update(os.environ)
    for key in list(env):
        if any(word in key for word in ("BRAINTRUST", "LANGFUSE", "SENTRY")):
            del env[key]
    env.pop("INTEGRATION_TESTS_MODE", None)
    env.update(
        {
            "POSTGRES_DB": f"{_BENCH_PREFIX}_db",
            "REDIS_DB_NUMBER": "10",
            "FILE_STORE_BACKEND": "s3",
            "S3_FILE_STORE_BUCKET_NAME": "chat-bench-file-store",
            "AUTH_TYPE": "basic",
            # A value for this run only.
            "USER_AUTH_SECRET": secrets.token_hex(32),
            "LOG_LEVEL": log_level,
            "DISABLE_TELEMETRY": "true",
            "SKIP_WARM_UP": "true",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(_BACKEND_DIR),
            "CHAT_BENCH_MOCK_LLM": mock_url,
        }
    )
    return env


# Packet fields that hold a duration, so they differ on each run.
_VOLATILE_KEYS = frozenset({"pre_answer_processing_seconds"})


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _VOLATILE_PATTERNS:
            value = pattern.sub("<time>", value)
        return value
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in sorted(value.items())
            if key not in _VOLATILE_KEYS
        }
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_normalize(value), sort_keys=True).encode()
    ).hexdigest()


def _line_kind(line: dict[str, Any]) -> str:
    obj = line.get("obj")
    if isinstance(obj, dict):
        return str(obj.get("type"))
    if "reserved_assistant_message_id" in line:
        return "message_ids"
    if "error" in line:
        return "error"
    if "chat_session_id" in line:
        return "session_id"
    return "+".join(sorted(line))


class Bench:
    def __init__(self, server_url: str, mock_url: str) -> None:
        self.server_url = server_url
        self.mock_url = mock_url
        self.client = httpx.Client(base_url=server_url, timeout=120)
        self.mock = httpx.Client(base_url=mock_url, timeout=30)

    # -- setup ---------------------------------------------------------------

    def sign_in(self) -> None:
        body = {"email": _EMAIL, "username": _EMAIL, "password": _PASSWORD}
        self.client.post("/auth/register", json=body).raise_for_status()
        self.client.post(
            "/auth/login", data={"username": _EMAIL, "password": _PASSWORD}
        ).raise_for_status()

    def create_llm_provider(self) -> None:
        response = self.client.put(
            "/admin/llm/provider?is_creation=true",
            json={
                "name": "chat-bench-mock",
                "provider": "openai_compatible",
                "api_key": "sk-chat-bench",
                "api_base": f"{self.mock_url}/scripts/{_SCRIPT_ID}/v1",
                "api_key_changed": True,
                "is_public": True,
                "model_configurations": [
                    {
                        "name": _MODEL_NAME,
                        "is_visible": True,
                        "max_input_tokens": 200_000,
                        "supports_image_input": False,
                    }
                ],
            },
        )
        response.raise_for_status()
        self.client.post(
            "/admin/llm/default",
            json={"provider_id": response.json()["id"], "model_name": _MODEL_NAME},
        ).raise_for_status()

    def reset_mock(self) -> None:
        script = {"conversations": [], "default_reply": {"text": _ANSWER}}
        self.mock.put(f"/scripts/{_SCRIPT_ID}", json=script).raise_for_status()

    def create_session(self) -> str:
        response = self.client.post(
            "/chat/create-chat-session",
            json={"persona_id": 0, "description": "chat bench"},
        )
        response.raise_for_status()
        return str(response.json()["chat_session_id"])

    def stats(self) -> dict[str, float]:
        response = self.client.get("/_bench/stats")
        response.raise_for_status()
        return response.json()

    def breakdown(self) -> dict[str, dict[str, int]]:
        response = self.client.get("/_bench/breakdown")
        response.raise_for_status()
        return response.json()

    def saved_answer(self, session_id: str) -> str | None:
        response = self.client.get(f"/chat/get-chat-session/{session_id}")
        response.raise_for_status()
        messages = response.json()["messages"]
        assistants = [m for m in messages if m["message_type"] == "assistant"]
        return assistants[-1]["message"] if assistants else None

    # -- one turn ------------------------------------------------------------

    def turn(self, session_id: str | None) -> TurnResult:
        self.reset_mock()
        body: dict[str, Any] = {"message": _QUESTION, "stream": True}
        if session_id is None:
            body["chat_session_info"] = {
                "persona_id": 0,
                "description": "chat bench",
            }
        else:
            body["chat_session_id"] = session_id

        lines: list[dict[str, Any]] = []
        answer: list[str] = []
        first_line_at: float | None = None
        first_token_at: float | None = None
        stop_at: float | None = None

        sent_at = time.monotonic()
        with self.client.stream(
            "POST", "/chat/send-chat-message", json=body
        ) as response:
            headers_at = time.monotonic()
            response.raise_for_status()
            for raw in response.iter_lines():
                if not raw:
                    continue
                now = time.monotonic()
                line = json.loads(raw)
                lines.append(line)
                if first_line_at is None:
                    first_line_at = now
                obj = line.get("obj") or {}
                if obj.get("type") == "message_delta" and obj.get("content"):
                    answer.append(obj["content"])
                    if first_token_at is None:
                        first_token_at = now
                if obj.get("type") == "stop" and stop_at is None:
                    stop_at = now
        closed_at = time.monotonic()

        state = self.mock.get(f"/scripts/{_SCRIPT_ID}").json()
        requests = state["requests"]
        first_request = requests[0] if requests else None

        def ms(moment: float | None) -> float | None:
            return None if moment is None else (moment - sent_at) * 1000

        pre_llm = llm = post_llm = None
        if first_request and first_request["first_text_at"] and first_token_at:
            pre_llm = (first_request["received_at"] - sent_at) * 1000
            llm = (first_request["first_text_at"] - first_request["received_at"]) * 1000
            post_llm = (first_token_at - first_request["first_text_at"]) * 1000

        kinds = [_line_kind(line) for line in lines]
        ids = next(
            (line for line in lines if "reserved_assistant_message_id" in line), {}
        )
        new_session = next(
            (line for line in lines if "chat_session_id" in line and "obj" not in line),
            {},
        )
        transcript = [
            {"kind": kind, "obj": line.get("obj"), "placement": line.get("placement")}
            for kind, line in zip(kinds, lines, strict=True)
            if kind not in ("message_ids", "session_id")
        ]
        return TurnResult(
            session_id=session_id or str(new_session.get("chat_session_id")),
            line_kinds=kinds,
            answer="".join(answer),
            errors=[json.dumps(line) for line in lines if "error" in line],
            stops=kinds.count("stop"),
            llm_requests=len(requests),
            request_digest=_digest(first_request["body"]) if first_request else None,
            transcript_digest=_digest(transcript),
            reserved_assistant_message_id=ids.get("reserved_assistant_message_id"),
            headers_ms=ms(headers_at) or 0.0,
            first_line_ms=ms(first_line_at) or 0.0,
            first_token_ms=ms(first_token_at),
            stop_ms=ms(stop_at),
            close_ms=ms(closed_at) or 0.0,
            pre_llm_ms=pre_llm,
            llm_ms=llm,
            post_llm_ms=post_llm,
        )


def _median(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(statistics.median(present), 2) if present else None


def _p95(values: list[float | None]) -> float | None:
    present = sorted(value for value in values if value is not None)
    if not present:
        return None
    return round(present[min(len(present) - 1, int(len(present) * 0.95))], 2)


def _run_scenario(bench: Bench, name: str, turns: int) -> dict[str, Any]:
    """Prepares the sessions, then measures `turns` turns one after the other."""
    sessions: list[str | None]
    if name == "warm":
        # The second turn of a session that holds one earlier exchange.
        sessions = []
        for _ in range(turns):
            session_id = bench.create_session()
            bench.turn(session_id)
            sessions.append(session_id)
    elif name == "new-session":
        sessions = [None] * turns
    elif name == "long-history":
        session_id = bench.create_session()
        for _ in range(_LONG_HISTORY_TURNS):
            bench.turn(session_id)
        sessions = [session_id] * turns
    else:
        raise ValueError(f"Unknown scenario {name}")

    before = bench.stats()
    breakdown_before = bench.breakdown()
    started = time.monotonic()
    results = [bench.turn(session_id) for session_id in sessions]
    elapsed = time.monotonic() - started
    after = bench.stats()
    breakdown_after = bench.breakdown()

    def per_turn_breakdown(kind: str, top: int) -> dict[str, float]:
        difference = {
            key: (count - breakdown_before[kind].get(key, 0)) / turns
            for key, count in breakdown_after[kind].items()
        }
        ranked = sorted(difference.items(), key=lambda item: -item[1])
        return {key: round(value, 2) for key, value in ranked[:top] if value > 0}

    per_turn = {
        key: round((after[key] - before[key]) / turns, 3)
        for key in before
        if key not in ("rss_mb", "threads_alive")
    }
    per_turn["cpu_ms"] = round(
        (per_turn.pop("cpu_user_seconds") + per_turn.pop("cpu_system_seconds")) * 1000,
        2,
    )
    saved = [bench.saved_answer(result.session_id) for result in results[-3:]]
    timings = [result.model_dump() for result in results]
    return {
        "turns": turns,
        "elapsed_seconds": round(elapsed, 2),
        "per_turn": per_turn,
        "rss_mb": round(after["rss_mb"], 1),
        "rss_growth_mb": round(after["rss_mb"] - before["rss_mb"], 1),
        "threads_alive": after["threads_alive"],
        "timings_ms": {
            key: {
                "median": _median([timing[key] for timing in timings]),
                "p95": _p95([timing[key] for timing in timings]),
            }
            for key in (
                "first_token_ms",
                "pre_llm_ms",
                "llm_ms",
                "post_llm_ms",
                "headers_ms",
                "first_line_ms",
                "stop_ms",
                "close_ms",
            )
        },
        "breakdown_per_turn": {
            "sql_statements": per_turn_breakdown("sql_statements", 200),
            "cache_commands": per_turn_breakdown("cache_commands", 50),
            "stack_samples": per_turn_breakdown("stack_samples", 400),
        },
        "results": [result.model_dump() for result in results],
        "saved_answers": saved,
    }


def _check_scenario(
    gates: Gates,
    name: str,
    entry: dict[str, Any],
    golden: dict[str, Any],
    update_golden: bool,
) -> None:
    results = [TurnResult.model_validate(r) for r in entry["results"]]
    turns = len(results)

    def count(predicate: Any) -> int:
        return sum(1 for result in results if predicate(result))

    gates.check(
        f"{name}: no error line",
        count(lambda r: r.errors) == 0,
        next((r.errors[0] for r in results if r.errors), ""),
    )
    gates.check(
        f"{name}: one stop per turn",
        count(lambda r: r.stops == 1) == turns,
        str(sorted({r.stops for r in results})),
    )
    gates.check(
        f"{name}: the answer is the mock answer",
        count(lambda r: r.answer == _ANSWER) == turns,
    )
    gates.check(
        f"{name}: one LLM request per turn",
        count(lambda r: r.llm_requests == 1) == turns,
        str(sorted({r.llm_requests for r in results})),
    )

    def ids_before_answer(result: TurnResult) -> bool:
        kinds = result.line_kinds
        return (
            result.reserved_assistant_message_id is not None
            and "message_start" in kinds
            and kinds.index("message_ids") < kinds.index("message_start")
        )

    gates.check(
        f"{name}: the reserved id comes before the answer",
        count(ids_before_answer) == turns,
    )
    gates.check(
        f"{name}: the saved answer equals the stream",
        all(saved == _ANSWER for saved in entry["saved_answers"]),
    )

    transcripts = sorted({r.transcript_digest for r in results})
    gates.check(
        f"{name}: every turn has the same transcript",
        len(transcripts) == 1,
        f"{len(transcripts)} different",
    )
    # The request holds the history, so it is the same only at a fixed depth.
    requests = sorted({r.request_digest or "" for r in results})
    if name != "long-history":
        gates.check(
            f"{name}: every turn sends the same LLM request",
            len(requests) == 1,
            f"{len(requests)} different",
        )

    current = {
        "transcript_digest": transcripts[0],
        "first_request_digest": results[0].request_digest,
        "sql_statements": entry["per_turn"]["sql_statements"],
        "sql_commits": entry["per_turn"]["sql_commits"],
        "cache_commands": entry["per_turn"]["cache_commands"],
        "threads_started": entry["per_turn"]["threads_started"],
    }
    if update_golden:
        golden[name] = current
        return
    expected = golden.get(name)
    if expected is None:
        gates.check(
            f"{name}: golden",
            False,
            "no golden value for this scenario; run with --update-golden",
        )
        return
    for field in ("transcript_digest", "first_request_digest"):
        gates.check(
            f"{name}: {field} equals golden",
            current[field] == expected.get(field),
            f"{current[field]} vs golden {expected.get(field)}",
        )
    for field in ("sql_statements", "sql_commits", "cache_commands", "threads_started"):
        gates.check(
            f"{name}: {field} per turn not above golden",
            # The server also runs a few statements of its own between turns.
            current[field] <= expected.get(field, 0) + 1.0,
            f"{current[field]} vs golden {expected.get(field)}",
        )


def _print_scenario(name: str, entry: dict[str, Any]) -> None:
    timings = entry["timings_ms"]
    per_turn = entry["per_turn"]

    def pair(key: str) -> str:
        return f"{timings[key]['median']} / {timings[key]['p95']}"

    print(f"\nScenario {name}: {entry['turns']} turns")
    print(f"  CPU per turn:        {per_turn['cpu_ms']} ms")
    print(
        f"  Per turn:            {per_turn['sql_statements']} SQL statements, "
        f"{per_turn['sql_commits']} commits, "
        f"{per_turn['sql_connections_checked_out']} connection checkouts, "
        f"{per_turn['cache_commands']} cache commands, "
        f"{per_turn['threads_started']} threads"
    )
    print(f"  First token ms:      {pair('first_token_ms')}  (median / p95)")
    print(f"    before the LLM:    {pair('pre_llm_ms')}")
    print(f"    in the mock LLM:   {pair('llm_ms')}")
    print(f"    after the LLM:     {pair('post_llm_ms')}")
    print(f"  Stop ms:             {pair('stop_ms')}")
    print(f"  Body closed ms:      {pair('close_ms')}")
    print(
        f"  Server RSS:          {entry['rss_mb']} MB ({entry['rss_growth_mb']:+} MB)"
    )


def _wait_for(url: str, process: subprocess.Popen[bytes], name: str, log: Path) -> None:
    deadline = time.monotonic() + 300
    while True:
        if process.poll() is not None:
            print(f"The {name} exited; see {log}")
            sys.exit(1)
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            print(f"The {name} did not start; see {log}")
            sys.exit(1)
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=",".join(_SCENARIOS))
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--max-swap-pct", type=float, default=50.0)
    parser.add_argument("--allow-swap", action="store_true")
    parser.add_argument("--update-golden", action="store_true")
    parser.add_argument(
        "--sample-ms",
        type=float,
        help="sample the stacks of the server at this interval; slows the run",
    )
    parser.add_argument("--log-level", default="warning")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    scenarios = [name.strip() for name in args.scenarios.split(",") if name.strip()]
    for name in scenarios:
        if name not in _SCENARIOS:
            parser.error(f"unknown scenario {name}")

    swap_pct = psutil.swap_memory().percent
    timings_valid = swap_pct <= args.max_swap_pct
    if not timings_valid and not args.allow_swap:
        print(
            f"Host swap is {swap_pct}% used, above --max-swap-pct. Timings would "
            "not be valid. Free memory, or pass --allow-swap to run the gates."
        )
        sys.exit(2)

    # One run at a time on the machine, shared with the docprocessing benchmark.
    lock_file = open(_LOCK_PATH, "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)

    log_dir = Path(tempfile.mkdtemp(prefix="chat-bench-"))
    server_log = log_dir / "api_server.log"
    print(f"Scenarios {', '.join(scenarios)}; logs in {log_dir}")

    gates = Gates()
    report: dict[str, Any] = {
        "host_swap_pct": swap_pct,
        "timings_valid": timings_valid,
        "log_dir": str(log_dir),
        "scenarios": {},
    }
    golden: dict[str, Any] = (
        json.loads(_GOLDEN_PATH.read_text()) if _GOLDEN_PATH.exists() else {}
    )

    mock_port = _free_port()
    mock_url = f"http://127.0.0.1:{mock_port}"
    # A process of its own, started as a module: scripts must not import tests.
    # time.monotonic() is one clock for all processes of the host.
    mock = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.integration.mock_services.mock_llm_server.server",
        ],
        cwd=_BACKEND_DIR,
        env={
            **os.environ,
            "PYTHONPATH": str(_BACKEND_DIR),
            "MOCK_LLM_SERVER_HOST": "127.0.0.1",
            "MOCK_LLM_SERVER_PORT": str(mock_port),
        },
        stdout=open(log_dir / "mock_llm.log", "w"),
        stderr=subprocess.STDOUT,
    )
    server: subprocess.Popen[bytes] | None = None
    try:
        _wait_for(f"{mock_url}/health", mock, "mock LLM", log_dir / "mock_llm.log")
        env = _bench_env(mock_url, args.log_level)
        if args.sample_ms:
            env["CHAT_BENCH_SAMPLE_MS"] = str(args.sample_ms)
        print("Setup: database, migrations...")
        setup = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.chat_bench.setup_worker",
                f"{_BENCH_PREFIX}_index",
            ],
            cwd=_BACKEND_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=open(log_dir / "setup.log", "w"),
            text=True,
        )
        if setup.returncode != 0:
            print(f"Setup failed; see {log_dir / 'setup.log'}")
            sys.exit(1)
        report["setup"] = json.loads(setup.stdout.strip().splitlines()[-1])

        port = _free_port()
        server_url = f"http://127.0.0.1:{port}"
        server = subprocess.Popen(
            [sys.executable, "-m", "scripts.chat_bench.server", str(port)],
            cwd=_BACKEND_DIR,
            env=env,
            stdout=open(server_log, "w"),
            stderr=subprocess.STDOUT,
        )
        print("Starting the API server...")
        _wait_for(f"{server_url}/health", server, "API server", server_log)

        bench = Bench(server_url, mock_url)
        bench.sign_in()
        bench.create_llm_provider()

        cold = bench.turn(bench.create_session())
        report["cold_turn"] = cold.model_dump()
        print(
            f"\nFirst turn of the process: first token after "
            f"{cold.first_token_ms and round(cold.first_token_ms)} ms"
        )
        for _ in range(_WARM_UP_TURNS):
            bench.turn(bench.create_session())

        for name in scenarios:
            entry = _run_scenario(bench, name, args.turns)
            report["scenarios"][name] = entry
            _print_scenario(name, entry)
            _check_scenario(gates, name, entry, golden, args.update_golden)

        gates.check(
            "API server still runs",
            server.poll() is None,
            f"exit code {server.poll()}",
        )
    finally:
        for process in (server, mock):
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()

    log_text = server_log.read_text(errors="replace")
    gates.check(
        "no traceback in the API server log",
        "Traceback (most recent call last)" not in log_text,
        str(server_log),
    )

    print("\nGates:")
    for result in gates.results:
        mark = "PASS" if result["passed"] else "FAIL"
        detail = f"  ({result['detail']})" if result["detail"] else ""
        print(f"  {mark}  {result['gate']}{detail if not result['passed'] else ''}")
    report["gates"] = gates.results

    if not timings_valid:
        print(
            f"\nHost swap was {swap_pct}% used: the gates and the counts are valid, "
            "the timings are not."
        )
    if args.update_golden and not gates.failed:
        _GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
        print(f"\nWrote golden values to {_GOLDEN_PATH}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))
    sys.exit(1 if gates.failed else 0)


if __name__ == "__main__":
    main()
