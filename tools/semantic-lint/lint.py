"""semantic-lint. Review a pull request against rules mined from Onyx reviewers.

python3 tools/semantic-lint/lint.py pr NUMBER [--publish] [--comment-out FILE]
python3 tools/semantic-lint/lint.py eval [--rule ID ...] [--write] [--seed DIR ...]
python3 tools/semantic-lint/lint.py check
"""

import argparse
import math
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from semantic_lint.diff import Added
from semantic_lint.evaluate import (
    CACHE_DIR,
    JEV_CACHE_FILE,
    CachedJev,
    EvalData,
    RuleResult,
    Scored,
    run_eval,
)
from semantic_lint.github import GitHub
from semantic_lint.registry import Registry, RuleId, load_registry
from semantic_lint.review import (
    Failed,
    Llm,
    Outcome,
    Report,
    Skipped,
    check_run,
    render_summary,
    review,
)
from semantic_lint.screen import Jev, Mode, Usage, active_threshold, rule_mode

DEFAULT_REPO: str = "onyx-dot-app/onyx"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pr_parser = commands.add_parser("pr", help="review one pull request")
    pr_parser.add_argument("number", type=int)
    pr_parser.add_argument("--repo", default=DEFAULT_REPO)
    pr_parser.add_argument("--publish", action="store_true", help="post the check run")
    pr_parser.add_argument("--comment-out", type=Path, help="write the summary here")
    eval_parser = commands.add_parser("eval", help="measure rules and set thresholds")
    eval_parser.add_argument("--rule", action="append", default=[])
    eval_parser.add_argument("--write", action="store_true")
    eval_parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    eval_parser.add_argument(
        "--seed", type=Path, action="append", default=[], help="read-only data dir"
    )
    eval_parser.add_argument("--repo", default=DEFAULT_REPO)
    commands.add_parser("check", help="validate the rule registry")
    args = parser.parse_args(argv)

    registry = load_registry()
    match args.command:
        case "pr":
            return _pr(registry, args)
        case "eval":
            return _eval(registry, args)
        case "check":
            return _check(registry)
    return 2


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _github_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _pr(registry: Registry, args: argparse.Namespace) -> int:
    github = GitHub(_require_env("GITHUB_TOKEN"), args.repo)
    head_sha = github.head_sha(args.number)
    outcome = _review(github, registry, args.number)
    if isinstance(outcome, Report):
        head_sha = outcome.pr.head_sha
    summary = render_summary(outcome, registry, head_sha)
    print(summary)
    if args.comment_out is not None:
        args.comment_out.write_text(summary)
    if args.publish:
        if github.publish_check_run(
            args.number, check_run(outcome, registry, head_sha)
        ):
            print(f"Published the check run on {head_sha}.", file=sys.stderr)
        else:
            print("The PR head moved. Published nothing.", file=sys.stderr)
    return 0


def _review(github: GitHub, registry: Registry, number: int) -> Outcome:
    """Every failure becomes an outcome, so the check run is always neutral or success."""
    missing = [
        name
        for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        return Skipped(f"{' and '.join(missing)} not set.")
    try:
        pr = github.pull_request(number)
        jev = Jev(os.environ["TYPESAFE_API_KEY"])
        return review(pr, registry, jev, Llm(os.environ["OPENAI_API_KEY"]))
    except Exception as error:
        traceback.print_exc()
        return Failed(f"{type(error).__name__}: {error}")


def _eval(registry: Registry, args: argparse.Namespace) -> int:
    token = _github_token()
    data = EvalData(args.cache, args.seed, GitHub(token, args.repo) if token else None)
    jev = CachedJev(Jev(_require_env("TYPESAFE_API_KEY")), args.cache / JEV_CACHE_FILE)
    rule_ids = [RuleId(rule_id) for rule_id in args.rule]
    results, usage = run_eval(registry, rule_ids, data, jev, args.write)
    print(
        f"{'rule':<52} {'pos':>4} {'neg':>6} {'thr':>5}  "
        f"{'tune P':>6} {'lower':>5} {'R':>5}  {'report P':>8} {'R':>5}  mode"
    )
    for result in results:
        print(_result_row(result))
    for result in results:
        print(f"\n{result.rule.id}")
        for item in result.worst_false_positives():
            print(f"  false positive  {_case_line(item)}")
        for item in result.worst_false_negatives():
            print(f"  false negative  {_case_line(item)}")
    print(f"\n{_usage_line('Jev', usage, registry.settings.prices.jev_input, 0.0)}")
    return 0


def _result_row(result: RuleResult) -> str:
    calibration = result.calibration
    tune, report = result.tune, result.report
    if calibration is None or tune is None or report is None:
        return (
            f"{result.rule.id:<52} {result.positives:>4} {result.negatives:>6} "
            f"{'-':>5}  too few tune positives"
        )
    return (
        f"{result.rule.id:<52} {result.positives:>4} {result.negatives:>6} "
        f"{calibration.threshold:>5.2f}  {_rate(tune.precision):>6} "
        f"{_rate(calibration.tune_precision_lower):>5} {_rate(tune.recall):>5}  "
        f"{_rate(report.precision):>8} {_rate(report.recall):>5}  {result.mode.value}"
        f"{' (written)' if result.written else ''}"
    )


def _rate(value: float) -> str:
    return "-" if math.isnan(value) else f"{value:.2f}"


def _case_line(item: Scored) -> str:
    window = item.case.window
    first_added = next(
        (
            line.text.strip()
            for line in window.lines
            if isinstance(line, Added) and line.text.strip()
        ),
        "",
    )
    return (
        f"p={item.p:.2f} #{item.case.pr} {window.path}:"
        f"{window.first_new_line}-{window.last_new_line}  {first_added[:70]}"
    )


def _usage_line(
    name: str, usage: Usage, input_price: float, output_price: float
) -> str:
    cost = (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1e6
    return (
        f"{name}: {usage.requests} requests, {usage.input_tokens:,} input tokens, "
        f"{usage.output_tokens:,} output tokens, ${cost:.4f}, {usage.seconds:.1f} s"
    )


def _check(registry: Registry) -> int:
    problems: list[str] = []
    for rule in registry.rules:
        if not rule.flag_examples:
            problems.append(f"{rule.id}: needs at least one [[flag]] example")
        cited = {flag.quote.comment for flag in rule.flag_examples if flag.quote}
        if cited - rule.sources:
            problems.append(
                f"{rule.id}: [[flag]] comments not in sources {cited - rule.sources}"
            )
        cleans = {clean.comment for clean in rule.clean_examples if clean.comment}
        if cleans - rule.sources - rule.near_misses:
            problems.append(
                f"{rule.id}: [[clean]] comments not in sources or near_misses"
            )
        if rule.calibration and active_threshold(rule, registry.settings) is None:
            problems.append(f"{rule.id}: stale calibration seal, rerun eval --write")
    for problem in problems:
        print(problem, file=sys.stderr)
    modes = [rule_mode(rule, registry.settings) for rule in registry.rules]
    print(
        f"{len(registry.rules)} rules: "
        + ", ".join(f"{modes.count(mode)} {mode.value}" for mode in Mode)
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
