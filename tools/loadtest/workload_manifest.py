"""Print the input and profile mix before a matched load comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from mock_llm.profiles import profile_kind, turn_profile
from onyx_client.messages import load_messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mock-profile-search-v1")
    parser.add_argument(
        "--seed", type=int, default=0, help="Must match MOCK_WORKLOAD_SEED"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(
        r"mock-profile-(chat|search|research|held)-v1(?:-agents[1-9][0-9]*)?",
        args.model,
    ):
        parser.error(
            "Use a base profile name; manifests do not model stress or fault overrides"
        )
    kind = profile_kind(args.model)
    if kind is None:
        parser.error("Select a representative profile model")
    questions = load_messages()
    plans = [turn_profile(kind, question, args.seed) for question in questions]
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
