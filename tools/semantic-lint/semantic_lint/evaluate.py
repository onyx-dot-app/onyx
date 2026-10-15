"""Measure each rule's screen on review history and choose its threshold.

Cases come from the diff of each cited comment's PR at the comment's commit
(GitHub compare base...commit), cut with the production cutter. A window that
holds a rule's source comment is a positive for that rule. Every other window
of those PRs is a negative. Comments a rule shows Jev as examples never grade
that rule. The PR number's hash puts each PR in the tune or the report split.

Eval reads Jev through an append-only answer cache, so a policy change or a
rerun costs nothing, and a question edit only asks the changed question.
"""

import hashlib
import json
import math
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path
from statistics import NormalDist

from semantic_lint.diff import (
    Added,
    Context,
    DiffLine,
    Removed,
    Window,
    cut_windows,
    parse_hunks,
)
from semantic_lint.github import base_sha, compare, review_comment
from semantic_lint.registry import (
    Calibration,
    CalibrationPolicy,
    CommentId,
    Registry,
    Rule,
    RuleId,
    Settings,
    precision_floor,
    write_calibration,
)
from semantic_lint.screen import (
    Jev,
    Mode,
    Usage,
    question_fingerprint,
    rule_mode,
    screen,
    seal,
)

__all__ = [
    "CACHE_DIR",
    "JEV_CACHE_FILE",
    "Case",
    "CachedJev",
    "EvalData",
    "Label",
    "Point",
    "RuleResult",
    "Scored",
    "Split",
    "build_cases",
    "choose_threshold",
    "run_eval",
    "split_of",
    "wilson_lower",
]

CACHE_DIR: Path = Path(__file__).resolve().parents[1] / ".cache"
JEV_CACHE_FILE: str = "jev_answers.jsonl"
COMMENTS_FILE: str = "pull_comments.jsonl"
DIFFS_DIR: str = "review_diffs"
WORST_CASES: int = 3


class Split(StrEnum):
    TUNE = "tune"
    REPORT = "report"


class Label(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


def split_of(pr: int, report_percent: int) -> Split:
    bucket = int(hashlib.sha256(str(pr).encode()).hexdigest(), 16) % 100
    return Split.REPORT if bucket < report_percent else Split.TUNE


@dataclass(frozen=True)
class ReviewComment:
    id: CommentId
    pr: int
    path: str
    commit: str
    # The commented line, the last line of the comment's diff_hunk.
    anchor: DiffLine


@dataclass(frozen=True)
class Case:
    window: Window
    pr: int
    split: Split
    positive_for: frozenset[RuleId]
    excluded_for: frozenset[RuleId]

    def label(self, rule_id: RuleId) -> Label | None:
        if rule_id in self.excluded_for:
            return None
        return Label.POSITIVE if rule_id in self.positive_for else Label.NEGATIVE


class EvalData:
    """Review comments and review-time diffs, read through a local cache.

    Reads `cache_dir`, then each seed directory (such as a mined corpus with the
    same layout), then GitHub through `gh`. Fetched rows go to `cache_dir` only.
    """

    def __init__(self, cache_dir: Path, seed_dirs: Sequence[Path], repo: str) -> None:
        self._dirs: tuple[Path, ...] = (cache_dir, *seed_dirs)
        self._cache_dir: Path = cache_dir
        self._repo: str = repo

    def comments(self, ids: Iterable[CommentId]) -> dict[CommentId, ReviewComment]:
        wanted = set(ids)
        rows: dict[int, dict[str, object]] = {}
        for directory in self._dirs:
            file = directory / COMMENTS_FILE
            if not file.exists():
                continue
            with file.open() as lines:
                for row in map(json.loads, lines):
                    if row["id"] in wanted:
                        rows.setdefault(row["id"], row)
        for comment_id in sorted(wanted - set(rows)):
            payload = review_comment(self._repo, comment_id)
            if payload is None:
                continue
            row = {
                "id": comment_id,
                "pr": int(payload["pull_request_url"].rsplit("/", 1)[1]),
                "path": payload["path"],
                "commit_id": payload["commit_id"],
                "diff_hunk": payload["diff_hunk"],
            }
            self._append(COMMENTS_FILE, row)
            rows[comment_id] = row
        comments = (_parse_comment(row) for row in rows.values())
        return {comment.id: comment for comment in comments if comment}

    def review_diff(self, pr: int, commit: str) -> list[tuple[str, str]]:
        """(path, patch) for every file with a patch in base...commit of the PR."""
        name = f"{pr}_{commit}.json"
        payload = next(
            (
                json.loads(path.read_text())
                for directory in self._dirs
                if (path := directory / DIFFS_DIR / name).exists()
            ),
            None,
        )
        if payload is None:
            payload = compare(self._repo, base_sha(self._repo, pr), commit)
            target = self._cache_dir / DIFFS_DIR / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload))
        return [
            (item["filename"], item["patch"])
            for item in payload["files"]
            if item.get("patch")
        ]

    def _append(self, file_name: str, row: Mapping[str, object]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with (self._cache_dir / file_name).open("a") as file:
            file.write(json.dumps(row) + "\n")


def _parse_comment(row: Mapping[str, object]) -> ReviewComment | None:
    hunk, commit = row.get("diff_hunk"), row.get("commit_id")
    if not isinstance(hunk, str) or not isinstance(commit, str):
        return None
    hunks = parse_hunks(hunk)
    if not hunks or not hunks[-1].lines:
        return None
    return ReviewComment(
        id=CommentId(int(str(row["id"]))),
        pr=int(str(row["pr"])),
        path=str(row["path"]),
        commit=commit,
        anchor=hunks[-1].lines[-1],
    )


def _anchor_window(comment: ReviewComment, windows: Sequence[Window]) -> Window | None:
    """The window at the comment's commit that holds the commented line.

    The corpus `commit_id` can be a later commit than the one the comment was
    written on, so the line is found by its text, nearest its original number.
    """
    best: tuple[int, Window] | None = None
    for window in windows:
        if window.path != comment.path:
            continue
        for line in window.lines:
            distance = _distance(comment.anchor, line)
            if distance is not None and (best is None or distance < best[0]):
                best = (distance, window)
    return best[1] if best else None


def _distance(anchor: DiffLine, line: DiffLine) -> int | None:
    if anchor.text != line.text:
        return None
    match anchor, line:
        case Removed(), Removed():
            return abs(anchor.old_line - line.old_line)
        case Added() | Context(), Added() | Context():
            return abs(anchor.new_line - line.new_line)
    return None


def build_cases(
    registry: Registry, data: EvalData
) -> tuple[list[Case], frozenset[CommentId]]:
    """Cases from the PRs every rule cites, and the cited comments with no window."""
    rules = registry.rules
    cited = {c for rule in rules for c in rule.sources | rule.near_misses}
    comments = data.comments(cited)
    max_lines = registry.settings.window.max_lines
    windows_by_pr: dict[int, dict[str, Window]] = {}
    anchored: dict[str, set[CommentId]] = {}
    for pr, commit in sorted({(c.pr, c.commit) for c in comments.values()}):
        windows = [
            window
            for path, patch in data.review_diff(pr, commit)
            for window in cut_windows(path, patch, max_lines)
        ]
        windows_by_pr.setdefault(pr, {}).update((w.id, w) for w in windows)
        for comment in comments.values():
            if (comment.pr, comment.commit) == (pr, commit):
                if window := _anchor_window(comment, windows):
                    anchored.setdefault(window.id, set()).add(comment.id)
    shown = {rule.id: rule.shown_comments for rule in rules}
    cases: list[Case] = []
    for pr, windows in sorted(windows_by_pr.items()):
        split = split_of(pr, registry.settings.calibration.report_percent)
        for window_id, window in windows.items():
            here = anchored.get(window_id, set())
            cases.append(
                Case(
                    window=window,
                    pr=pr,
                    split=split,
                    positive_for=frozenset(r.id for r in rules if r.sources & here),
                    excluded_for=frozenset(r.id for r in rules if shown[r.id] & here),
                )
            )
    found = {comment for here in anchored.values() for comment in here}
    return cases, frozenset(cited - found)


class CachedJev(Jev):
    """Jev behind an append-only JSONL cache keyed by window, question and model."""

    def __init__(self, inner: Jev, cache_file: Path) -> None:
        super().__init__(api_key="")
        self._inner: Jev = inner
        self._file: Path = cache_file
        self._lock: threading.Lock = threading.Lock()
        self._answers: dict[tuple[str, str, str], float] = {}
        if cache_file.exists():
            with cache_file.open() as lines:
                for row in map(json.loads, lines):
                    key = (row["window"], row["question"], row["model"])
                    self._answers[key] = row["p"]

    def ask(
        self, model: str, window: Window, rules: Sequence[Rule]
    ) -> tuple[dict[RuleId, float], Usage]:
        keys = {
            rule.id: (window.id, question_fingerprint(rule), model) for rule in rules
        }
        known = {
            rule_id: self._answers[key]
            for rule_id, key in keys.items()
            if key in self._answers
        }
        missing = [rule for rule in rules if rule.id not in known]
        if not missing:
            return known, Usage()
        asked, usage = self._inner.ask(model, window, missing)
        with self._lock:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with self._file.open("a") as file:
                for rule_id, p in asked.items():
                    window_id, question, _ = keys[rule_id]
                    self._answers[keys[rule_id]] = p
                    row = {"window": window_id, "question": question, "model": model}
                    file.write(json.dumps(row | {"p": p}) + "\n")
        return known | asked, usage


@dataclass(frozen=True)
class Point:
    threshold: float
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        flagged = self.true_positives + self.false_positives
        return self.true_positives / flagged if flagged else math.nan

    @property
    def recall(self) -> float:
        positives = self.true_positives + self.false_negatives
        return self.true_positives / positives if positives else math.nan


def wilson_lower(successes: int, trials: int, confidence: float) -> float:
    """Lower bound of the two-sided Wilson score interval."""
    if trials == 0:
        return 0.0
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    rate = successes / trials
    denominator = 1 + z * z / trials
    centre = rate + z * z / (2 * trials)
    spread = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
    return (centre - spread) / denominator


def _point(scored: Sequence[tuple[float, Label]], threshold: float) -> Point:
    flagged = [label for p, label in scored if p >= threshold]
    positives = sum(label is Label.POSITIVE for _, label in scored)
    true_positives = sum(label is Label.POSITIVE for label in flagged)
    return Point(
        threshold,
        true_positives,
        len(flagged) - true_positives,
        positives - true_positives,
    )


def choose_threshold(
    tune: Sequence[tuple[float, Label]], policy: CalibrationPolicy, floor: float
) -> Point | None:
    """The lowest threshold whose precision lower bound meets `floor`.

    Every candidate keeps at least `min_positives` true positives. When none
    meets the floor, the one with the best lower bound, which runs in shadow.
    None when the tune split has too few positives.
    """
    candidates = [
        point
        for point in (_point(tune, p) for p in sorted({p for p, _ in tune}))
        if point.true_positives >= policy.min_positives
    ]
    if not candidates:
        return None

    def lower(point: Point) -> float:
        flagged = point.true_positives + point.false_positives
        return wilson_lower(point.true_positives, flagged, policy.confidence)

    passing = [point for point in candidates if lower(point) >= floor]
    if passing:
        return passing[0]
    return max(candidates, key=lambda point: (lower(point), -point.threshold))


@dataclass(frozen=True)
class Scored:
    case: Case
    label: Label
    p: float


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    scored: tuple[Scored, ...]
    calibration: Calibration | None
    # Source comments with no window at their commit (code changed, or deleted).
    unanchored_sources: int
    tune: Point | None
    report: Point | None
    mode: Mode
    written: bool

    @property
    def positives(self) -> int:
        return sum(item.label is Label.POSITIVE for item in self.scored)

    @property
    def negatives(self) -> int:
        return sum(item.label is Label.NEGATIVE for item in self.scored)

    def worst_false_positives(self) -> list[Scored]:
        negatives = [s for s in self.scored if s.label is Label.NEGATIVE]
        return sorted(negatives, key=lambda s: s.p, reverse=True)[:WORST_CASES]

    def worst_false_negatives(self) -> list[Scored]:
        positives = [s for s in self.scored if s.label is Label.POSITIVE]
        return sorted(positives, key=lambda s: s.p)[:WORST_CASES]


def run_eval(
    full: Registry,
    rule_ids: Sequence[RuleId] | None,
    data: EvalData,
    jev: Jev,
    write: bool,
) -> tuple[list[RuleResult], Usage]:
    """Score the chosen rules on cases built from every rule's PRs.

    The case set comes from the full registry, so a rule's threshold does not
    depend on which other rules ran beside it.
    """
    selected = full.only(rule_ids) if rule_ids else full
    cases, unanchored = build_cases(full, data)
    screening = screen([case.window for case in cases], selected, jev)
    scores: dict[tuple[str, RuleId], float] = {
        (score.window_id, score.rule_id): score.p for score in screening.scores
    }
    results = [
        _result(rule, cases, scores, unanchored, full.settings, write)
        for rule in selected.rules
    ]
    return results, screening.usage


def _result(
    rule: Rule,
    cases: Sequence[Case],
    scores: Mapping[tuple[str, RuleId], float],
    unanchored: frozenset[CommentId],
    settings: Settings,
    write: bool,
) -> RuleResult:
    scored = tuple(
        Scored(case, label, scores[(case.window.id, rule.id)])
        for case in cases
        if (case.window.id, rule.id) in scores
        and (label := case.label(rule.id)) is not None
    )
    tune = [(s.p, s.label) for s in scored if s.case.split is Split.TUNE]
    held_out = [(s.p, s.label) for s in scored if s.case.split is Split.REPORT]
    policy = settings.calibration
    chosen = choose_threshold(tune, policy, precision_floor(rule, settings))
    report = _point(held_out, chosen.threshold) if chosen else None
    calibration = (
        Calibration(
            threshold=round(chosen.threshold, 4),
            precision=report.precision,
            recall=report.recall,
            positives=sum(s.label is Label.POSITIVE for s in scored),
            negatives=sum(s.label is Label.NEGATIVE for s in scored),
            tune_precision_lower=wilson_lower(
                chosen.true_positives,
                chosen.true_positives + chosen.false_positives,
                policy.confidence,
            ),
            jev_model=settings.jev_model,
            evaluated_on=date.today(),
            seal=seal(rule, round(chosen.threshold, 4), settings),
        )
        if chosen and report
        else None
    )
    calibrated = replace(rule, calibration=calibration)
    return RuleResult(
        rule=rule,
        scored=scored,
        calibration=calibration,
        unanchored_sources=len(rule.sources & unanchored),
        tune=chosen,
        report=report,
        mode=rule_mode(calibrated, settings),
        written=write_calibration(rule, calibration) if write else False,
    )
