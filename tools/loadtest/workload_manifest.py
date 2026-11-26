"""Print the input and profile mix before a matched load comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from mock_llm.profiles import profile_kind, turn_profile
from mock_llm.response_plan import KNOB_RE, Knobs
from onyx_client.messages import load_messages

# Flag suffixes that change a profile's plan.
MANIFEST_FLAGS: dict[str, set[str]] = {
    "search": {"codebatched"},
    "code": {"claude"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mock-profile-search-v1")
    parser.add_argument(
        "--seed", type=int, default=0, help="Must match MOCK_WORKLOAD_SEED"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        kind = profile_kind(args.model)
        knobs = Knobs(args.model)
    except ValueError as error:
        parser.error(str(error))
    if kind is None:
        parser.error("Select a representative profile model")
    # Base profile names with the suffixes that a manifest models, in any order.
    base = f"mock-profile-{kind}-v1"
    flags = set(KNOB_RE.sub("", args.model).removeprefix(base).split("-")) - {""}
    knob_names = {name for name, _ in KNOB_RE.findall(args.model)}
    if (
        not args.model.startswith(base)
        or not flags <= MANIFEST_FLAGS.get(kind, set())
        or not knob_names <= {"agents"} | ({"tail"} if kind == "code" else set())
    ):
        parser.error(
            "Use a base profile name; manifests do not model stress or fault overrides"
        )
    questions = load_messages()
    plans = [
        turn_profile(
            kind,
            question,
            args.seed,
            code_pool=knobs.code_pool,
            tail_percent=knobs.tail_percent,
        )
        for question in questions
    ]
    programs = [program for plan in plans for program in plan.programs]
    result = {
        "model": args.model,
        "seed": args.seed,
        "question_count": len(questions),
        "unique_questions": len(set(questions)),
        "corpus_sha256": hashlib.sha256(
            json.dumps(questions, ensure_ascii=False).encode()
        ).hexdigest(),
        "size_counts": dict(Counter(plan.size for plan in plans)),
        "search_round_counts": dict(Counter(plan.search_rounds for plan in plans)),
        "mean_answer_words": sum(plan.answer_words for plan in plans) / len(plans),
        "reasoning_turns": sum(plan.reasoning_words > 0 for plan in plans),
        "program_count_counts": dict(Counter(len(plan.programs) for plan in plans)),
        "programs": len(programs),
        "planned_output_chars": sum(program.output_chars for program in programs),
        "planned_program_searches": sum(program.searches for program in programs),
        "planned_failed_programs": sum(program.failed for program in programs),
        "plans": [asdict(plan) for plan in plans],
        "scope": "One pass through input questions; actual completed mix depends on load. No question text included.",
    }
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
