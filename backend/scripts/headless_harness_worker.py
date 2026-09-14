"""One direct-Python experiment arm; launched inside an isolated backend image."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
import time
import traceback
import uuid
from pathlib import Path

SECRET_VALUES = {
    value
    for key, value in os.environ.items()
    if any(
        part in key.upper()
        for part in ("PASSWORD", "TOKEN", "SECRET", "API_KEY", "CREDENTIAL")
    )
    and len(value) >= 8
}


def write_json(path: Path, value: object) -> None:
    encoded = json.dumps(value, indent=2, ensure_ascii=False)
    for secret in sorted(SECRET_VALUES, key=len, reverse=True):
        encoded = encoded.replace(
            json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]"
        )
    path.write_text(encoded + "\n")


class RecordingDecisionModel:
    """Capture the exact outer decision input without changing model behavior."""

    def __init__(self, inner, output: Path) -> None:
        self.inner = inner
        self.output = output
        self.sequence = 0

    def decide(self, **kwargs):
        self.sequence += 1
        directory = self.output / f"decision-{self.sequence:03d}"
        directory.mkdir()
        write_json(directory / "request.json", kwargs)
        started = time.monotonic()
        try:
            result = self.inner.decide(**kwargs)
            write_json(directory / "response.json", result.model_dump(mode="json"))
            return result
        except Exception as exc:
            write_json(directory / "error.json", {"error_type": type(exc).__name__})
            raise
        finally:
            write_json(
                directory / "timing.json",
                {"total_ms": (time.monotonic() - started) * 1000},
            )


def run(args: argparse.Namespace) -> int:
    # Suppress backend logs, which may contain connection details or provider errors.
    logging.disable(logging.CRITICAL)
    from onyx.agents.v2.llm import (
        BudgetedLLM,
        BudgetExceeded,
        BudgetLedger,
        OnyxDecisionModel,
        create_search_llm,
    )
    from onyx.agents.v2.models import ExecutionContext, HarnessPolicy
    from onyx.agents.v2.runner import AgentHarness
    from onyx.agents.v2.search import InternalSearchAnswer
    from onyx.db.harness_v2 import prepare_harness
    from onyx.db.headless_harness import prepare_headless_user
    from onyx.llm.factory import get_llm_token_counter
    from onyx.llm.models import ReasoningEffort
    from onyx.server.settings.store import load_settings

    output = Path(args.output)
    config = json.loads(Path(args.config).read_text())
    if config.get("record_llm_usage", False):
        from scripts.llm_usage_observer import install_usage_observer

        install_usage_observer(BudgetLedger, BudgetedLLM, output, write_json)
    if config.get("record_provider_wire", False):
        from scripts.provider_wire_observer import install_wire_observer

        install_wire_observer(output, write_json)
    if config.get("provider_reasoning_effort") is not None:
        from scripts.reasoning_effort_experiment import (
            install_reasoning_effort_override,
        )

        install_reasoning_effort_override(config["provider_reasoning_effort"])
    user, identity = prepare_headless_user(config.get("user_id"))
    if load_settings().auto_detect_search_filters is not False:
        raise ValueError(
            "Benchmark comparison requires automatic search filters disabled"
        )
    if args.arm == "preflight":
        write_json(output / "preflight.json", identity)
        return 0
    question = json.loads(Path(args.question).read_text())["question"]
    started = time.monotonic()
    prepared = prepare_harness(user, config["provider"], config["model"], None, False)
    if (
        config["model"] in {"gpt-5.6-luna", "gpt-5.6-sol"}
        and config["reasoning_effort"] == "off"
    ):
        prepared.llm = create_search_llm(prepared.llm, config["model"])
    if isinstance(prepared.llm.config.api_key, str) and prepared.llm.config.api_key:
        SECRET_VALUES.add(prepared.llm.config.api_key)
    counter = get_llm_token_counter(prepared.llm)
    policy_values = dict(config["policy"])
    # The standalone synthesis baseline retains its original execution policy.
    if args.arm == "baseline":
        policy_values.setdefault("duration_mode", "hard")
    policy = HarnessPolicy(**policy_values)
    search_llm = create_search_llm(
        prepared.llm, policy.search_model if args.arm == "candidate" else None
    )
    limit = int(prepared.llm.config.max_input_tokens * 0.9)
    policy = policy.model_copy(
        update={"max_context_tokens": min(policy.max_context_tokens or limit, limit)}
    )
    write_json(
        output / "effective.json",
        {
            **identity,
            "model": prepared.llm.config.model_name,
            "model_provider": prepared.llm.config.model_provider,
            "search_model": search_llm.config.model_name,
            "search_reasoning": "none"
            if args.arm == "candidate" and policy.search_model
            else "legacy",
            "provider_reasoning_effort": config.get("provider_reasoning_effort"),
            "search_min_output_tokens": config.get("search_min_output_tokens"),
            "policy": policy.model_dump(mode="json"),
            "reasoning_effort": config["reasoning_effort"],
            "auto_detect_filters": False,
            "filters": None,
            "persona_id": None,
            "index_implementation": type(prepared.index).__name__,
        },
    )
    cancellation = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancellation.set())
    signal.signal(signal.SIGINT, lambda *_: cancellation.set())
    shared_started_at = time.monotonic() if policy.duration_mode == "soft" else None
    ledger = BudgetLedger(
        policy, counter, cancelled=cancellation.is_set, started_at=shared_started_at
    )
    llm = BudgetedLLM(prepared.llm, ledger)
    search = InternalSearchAnswer(
        tool_id=prepared.search_tool_id,
        user=user,
        persona=prepared.persona,
        filters=None,
        index=prepared.index,
        llm=BudgetedLLM(
            search_llm,
            ledger,
            max_output_tokens=policy.search_max_output_tokens
            if args.arm == "candidate"
            else None,
            min_output_tokens=config.get("search_min_output_tokens")
            if args.arm == "candidate"
            else None,
            protected_tokens=policy.completion_reserve_tokens
            if policy.protect_search_budget
            else 0,
        ),
        reasoning_effort=ReasoningEffort(config["reasoning_effort"]),
        auto_detect_filters=False,
        synthesize_answer=args.arm == "baseline",
        feedback=policy.search_feedback,
        candidate_preparation=policy.search_candidate_preparation,
        hierarchical_selection=policy.search_hierarchical_selection,
        final_selection_limit=policy.search_final_selection_limit,
        document_read=policy.search_document_read,
        task_anchor=policy.search_task_anchor,
        record_queries=config.get("search_record_queries", False),
        expansion_strategy=config.get("search_expansion_strategy", "objective"),
    )
    sequence = 0

    def execute(arguments, context):
        nonlocal sequence
        sequence += 1
        call_dir = output / f"search-{sequence:03d}-{uuid.uuid4().hex[:8]}"
        call_dir.mkdir()
        write_json(
            call_dir / "request.json", {"arguments": arguments, "task": context.task}
        )
        call_started = time.monotonic()
        try:
            from onyx.tracing.framework.create import function_span

            with function_span(
                "internal_search", input=json.dumps(arguments)
            ) as search_span:
                result = search.run(arguments, context)
                search_span.span_data.output = json.dumps(
                    {
                        "receipt": result.receipt,
                        "citation_mapping": result.citation_mapping,
                        "retrieval_stages": search.last_diagnostics.get(
                            "retrieval", {}
                        ).get("selection_stage_document_ids", {}),
                    }
                )
            if search.last_diagnostics:
                write_json(
                    call_dir / "retrieval-diagnostics.json", search.last_diagnostics
                )
            # Capture before ContextState previewing, trimming, or store eviction.
            write_json(call_dir / "output.json", result.model_dump(mode="json"))
            return result
        finally:
            write_json(
                call_dir / "timing.json",
                {"total_ms": (time.monotonic() - call_started) * 1000},
            )

    setup_ms = (time.monotonic() - started) * 1000
    operation_started = time.monotonic()
    try:
        if config.get("fixed_evidence_replay", False):
            from scripts.replay_harness_evidence import replay

            result = replay(
                llm=llm,
                user_id=str(user.id),
                reasoning_effort=ReasoningEffort(config["reasoning_effort"]),
                output=output,
                ledger=ledger,
                write_json=write_json,
                source_cards=policy.source_cards,
                evidence_table=config.get("fixed_evidence_table", False),
            )
        elif args.arm == "candidate":
            registered = search.registered().model_copy(update={"execute": execute})
            harness = AgentHarness(
                model=RecordingDecisionModel(
                    OnyxDecisionModel(
                        llm,
                        source_cards=policy.source_cards,
                        user_id=str(user.id),
                        reasoning_effort=ReasoningEffort(config["reasoning_effort"]),
                        operation_timeout_seconds=policy.model_timeout_seconds
                        if policy.duration_mode == "soft"
                        else None,
                    ),
                    output,
                ),
                tools=[registered],
                policy=policy,
                usage=ledger.snapshot,
                token_counter=counter,
                cancelled=cancellation.is_set,
                started_at=shared_started_at,
            )
            result = harness.run(question).model_dump(mode="json")
            # The existing runner includes raw provider exception strings. Keep
            # the outcome and timing, but omit those messages from artifacts.
            if result["reason"].startswith("model failed:"):
                result["reason"] = "Model call failed (provider message omitted)"
            for event in result["events"]:
                if event["kind"] == "model_error":
                    message = event["data"].pop("reason", "")
                    event["data"]["error_category"] = (
                        "timeout"
                        if "timed out" in message.lower()
                        or "timeout" in message.lower()
                        else "model_error"
                    )
        else:
            if policy.duration_mode == "soft":
                raise ValueError(
                    "Soft duration experiment requires the candidate agent path"
                )
            response = execute(
                {"objective": question},
                ExecutionContext(
                    run_id=str(uuid.uuid4()),
                    task=question,
                    remaining_seconds=ledger.remaining_seconds(),
                    remaining_tokens=ledger.remaining_tokens(),
                    cancelled=lambda: ledger.remaining_seconds() <= 0,
                ),
            )
            result = {
                "outcome": "completed"
                if response.status == "success" and response.answer
                else "partial",
                "answer": response.answer or "",
                "receipts": [response.receipt],
                "document_ids": response.document_ids,
                "citation_mapping": response.citation_mapping,
                "tool_calls": 1,
                "model_calls": 0,
                "events": [],
                "usage": ledger.snapshot().model_dump(mode="json"),
            }
    except Exception as exc:
        # Deliberately omit exception text: upstream errors can embed credentials.
        result = {
            "outcome": "budget_exhausted"
            if isinstance(exc, BudgetExceeded)
            else "error",
            "error_type": type(exc).__name__,
            "answer": "",
            "usage": ledger.snapshot().model_dump(mode="json"),
        }
    result["duration_mode"] = policy.duration_mode
    result["target_seconds"] = policy.max_elapsed_seconds
    total_ms = result.get("total_ms", (time.monotonic() - operation_started) * 1000)
    if not isinstance(total_ms, (int, float)):
        total_ms = (time.monotonic() - operation_started) * 1000
    result["target_overshoot_seconds"] = max(
        0,
        total_ms / 1000 - policy.max_elapsed_seconds,
    )
    result.update(
        {
            "arm": args.arm,
            "setup_ms": setup_ms,
            "operation_ms": (time.monotonic() - operation_started) * 1000,
            "request_total_ms": (time.monotonic() - started) * 1000,
        }
    )
    write_json(output / "result.json", result)
    return 0 if result["outcome"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--question")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--arm", choices=["preflight", "baseline", "candidate"], required=True
    )
    args = parser.parse_args()
    try:
        from scripts.headless_braintrust import trace_question

        with trace_question(args, write_json):
            status = run(args)
    except Exception as exc:
        write_json(
            Path(args.output) / "failure.json",
            {
                "error_type": type(exc).__name__,
                "frames": [
                    {"file": f.filename, "line": f.lineno, "function": f.name}
                    for f in traceback.extract_tb(exc.__traceback__)
                ],
            },
        )
        status = 1
    # A fresh container per arm ensures abandoned timeout threads cannot overlap
    # the next arm. Remote provider work/billing may still continue.
    os._exit(status)
