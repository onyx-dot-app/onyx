"""Collect historical GitHub evidence and score manually verified findings."""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast, get_args

Reviewer = Literal["greptile", "cubic", "human"]
MatchStatus = Literal["fixed", "declined", "ignored", "unfixed", "unknown"]
ControlStatus = Literal["changed", "declined", "unchanged", "unknown"]
GitHubRecord = dict[str, object]


class CommitEntry(TypedDict):
    sha: str
    message: str


class Candidate(CommitEntry):
    pr: int
    references: list[int]


class ReviewEvidence(TypedDict):
    pr: GitHubRecord
    commits: list[GitHubRecord]
    reviews: list[GitHubRecord]
    inline: list[GitHubRecord]
    discussion: list[GitHubRecord]


class Match(TypedDict):
    comment: int
    status: MatchStatus


class OtherMatch(Match):
    reviewer: str


class Case(TypedDict):
    introduced: int
    fixed: int
    answer: str
    reviewed: list[Reviewer]
    matches: dict[Reviewer, Match]
    other_match: NotRequired[OtherMatch]


class ControlFinding(TypedDict):
    comment: int
    status: ControlStatus


class Control(TypedDict):
    pr: int
    findings: dict[Reviewer, list[ControlFinding]]


class Labels(TypedDict):
    cases: list[Case]
    excluded: NotRequired[dict[str, str]]
    controls: list[Control]


class ReviewerResult(TypedDict):
    cases: int
    reviewed_cases: int
    found: int
    lost: int
    unknown_match_outcome: int
    control_prs: int
    control_comments: int
    control_declined_or_unchanged: int
    control_unknown: int


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True)


def github(repo: str, endpoint: str) -> GitHubRecord:
    return json.loads(run("gh", "api", f"repos/{repo}/{endpoint}"))


def pages(repo: str, endpoint: str) -> list[GitHubRecord]:
    result = run(
        "gh", "api", "--paginate", "--slurp", f"repos/{repo}/{endpoint}?per_page=100"
    )
    page_rows: list[list[GitHubRecord]] = json.loads(result)
    return [row for page in page_rows for row in page]


def discover(ref: str, since: str, until: str) -> dict[int, CommitEntry]:
    log = run(
        "git",
        "log",
        ref,
        "--first-parent",
        f"--since={since}",
        f"--until={until}",
        "--format=%H%x09%B%x00",
    )
    commits: dict[int, CommitEntry] = {}
    for row in log.split("\0"):
        if not row.strip():
            continue
        sha, message = row.strip().split("\t", 1)
        title = message.splitlines()[0]
        pr = re.search(r"\(#(\d+)\)$", title)
        if pr:
            commits[int(pr[1])] = {"sha": sha, "message": message}
    return commits


def candidates(commits: dict[int, CommitEntry]) -> list[Candidate]:
    result: list[Candidate] = []
    for number, entry in commits.items():
        message = entry["message"]
        references = sorted(
            {int(value) for value in re.findall(r"(?:#|/pull/)(\d+)\b", message)}
            - {number}
        )
        if re.match(r"revert\b", message, re.IGNORECASE) or (
            re.search(
                r"\b(fix(?:es|ed)?|regression|broke|caused by)\b",
                message.splitlines()[0],
                re.IGNORECASE,
            )
            and (references or re.search(r"\b[a-f0-9]{10,40}\b", message))
        ):
            result.append({"pr": number, "references": references, **entry})
    return result


def load_labels(path: Path) -> Labels:
    labels = cast(Labels, json.loads(path.read_text()))
    for case in labels["cases"]:
        matches = list(case["matches"].values())
        if "other_match" in case:
            matches.append(case["other_match"])
        for match in matches:
            if match["status"] not in get_args(MatchStatus):
                raise ValueError(
                    f"{path}: case #{case['introduced']}, comment {match['comment']}: "
                    f"unsupported match status {match['status']!r}"
                )
    for control in labels["controls"]:
        for findings in control["findings"].values():
            for finding in findings:
                if finding["status"] not in get_args(ControlStatus):
                    raise ValueError(
                        f"{path}: control #{control['pr']}, comment {finding['comment']}: "
                        f"unsupported control status {finding['status']!r}"
                    )
    return labels


def score(labels: Labels) -> dict[Reviewer, ReviewerResult]:
    cases = labels["cases"]
    controls = labels["controls"]
    result: dict[Reviewer, ReviewerResult] = {}
    reviewers: tuple[Reviewer, ...] = ("greptile", "cubic", "human")
    for reviewer in reviewers:
        covered = sum(reviewer in case["reviewed"] for case in cases)
        hits = [
            case["matches"][reviewer] for case in cases if reviewer in case["matches"]
        ]
        roots = [
            finding
            for control in controls
            for finding in control["findings"].get(reviewer, [])
        ]
        result[reviewer] = {
            "cases": len(cases),
            "reviewed_cases": covered,
            "found": len(hits),
            "lost": sum(
                hit["status"] in {"declined", "ignored", "unfixed"} for hit in hits
            ),
            "unknown_match_outcome": sum(hit["status"] == "unknown" for hit in hits),
            "control_prs": len(controls),
            "control_comments": len(roots),
            "control_declined_or_unchanged": sum(
                root["status"] in {"declined", "unchanged"} for root in roots
            ),
            "control_unknown": sum(root["status"] == "unknown" for root in roots),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels", type=Path, default=Path(__file__).with_name("pilot.json")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("score")
    scan = subparsers.add_parser("discover")
    scan.add_argument("--ref", default="origin/main")
    scan.add_argument("--since", required=True)
    scan.add_argument("--until", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("prs", nargs="+", type=int)
    collect.add_argument("--repo", default="onyx-dot-app/onyx")
    args = parser.parse_args()
    output: list[Candidate] | dict[int, ReviewEvidence] | dict[Reviewer, ReviewerResult]
    if args.command == "discover":
        output = candidates(discover(args.ref, args.since, args.until))
    elif args.command == "collect":
        output = {
            pr: {
                "pr": github(args.repo, f"pulls/{pr}"),
                "commits": pages(args.repo, f"pulls/{pr}/commits"),
                "reviews": pages(args.repo, f"pulls/{pr}/reviews"),
                "inline": pages(args.repo, f"pulls/{pr}/comments"),
                "discussion": pages(args.repo, f"issues/{pr}/comments"),
            }
            for pr in args.prs
        }
    else:
        output = score(load_labels(args.labels))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
