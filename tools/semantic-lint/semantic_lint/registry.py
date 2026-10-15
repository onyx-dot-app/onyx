"""The rule registry, read from tools/semantic-lint/rules/.

One TOML file per rule. The file stem is the rule id, so two rules cannot
share an id. `registry.toml` beside the rules holds the shared settings. The
only part of a rule file the tool writes is its trailing `[calibration]` table.
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from functools import cache
from pathlib import Path, PurePosixPath
from typing import NewType

__all__ = [
    "RULES_DIR",
    "SETTINGS_FILE",
    "Budget",
    "Calibration",
    "CalibrationPolicy",
    "CleanExample",
    "CommentId",
    "EvalSettings",
    "Family",
    "FlagExample",
    "LlmSettings",
    "Prices",
    "Question",
    "Quote",
    "Registry",
    "RegistryError",
    "Rule",
    "RuleId",
    "Scope",
    "Settings",
    "Severity",
    "WindowSettings",
    "load_registry",
    "precision_floor",
    "write_calibration",
]

RULES_DIR: Path = Path(__file__).resolve().parents[1] / "rules"
SETTINGS_FILE: str = "registry.toml"
# One check run request carries at most 50 annotations.
MAX_ANNOTATIONS_PER_REQUEST: int = 50

RuleId = NewType("RuleId", str)
CommentId = NewType("CommentId", int)

_RULE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_CALIBRATION_HEADER = re.compile(r"^\[calibration\]\s*$", re.MULTILINE)
_TABLE_HEADER = re.compile(r"^\s*\[", re.MULTILINE)


class RegistryError(Exception):
    """A rule or settings file is invalid. The message names the file and key."""


class Severity(StrEnum):
    FIX = "fix"
    NIT = "nit"


class Family(StrEnum):
    WRAPPER = "wrapper"
    SIMPLIFY = "simplify"
    PLACEMENT = "placement"
    REUSE = "reuse"
    OTHER = "other"


@dataclass(frozen=True)
class Scope:
    paths: tuple[str, ...]
    exclude: tuple[str, ...]

    def covers(self, path: str) -> bool:
        return _matches(path, self.paths) and not _matches(path, self.exclude)


@cache
def _matches(path: str, globs: tuple[str, ...]) -> bool:
    posix = PurePosixPath(path)
    return any(posix.full_match(pattern) for pattern in globs)


@dataclass(frozen=True)
class Question:
    """One Jev noul. Its state is `{"file": <path>, "diff": <window text>}`."""

    instructions: str
    true_what: str
    true_not_for: tuple[str, ...]
    false_what: str
    false_not_for: tuple[str, ...]


@dataclass(frozen=True)
class Quote:
    comment: CommentId
    said: str


@dataclass(frozen=True)
class FlagExample:
    """Code the reviewers objected to. Jev sees `code`, the LLM also sees the quote."""

    code: str
    quote: Quote | None


@dataclass(frozen=True)
class CleanExample:
    """Look-alike code the reviewers accepted."""

    code: str
    comment: CommentId | None


@dataclass(frozen=True)
class Calibration:
    """Written only by `lint.py eval --write`.

    `precision` and `recall` are measured on the report split. They are NaN when
    the report split has no flagged window or no positive.
    """

    threshold: float
    precision: float
    recall: float
    positives: int
    negatives: int
    tune_precision_lower: float
    jev_model: str
    evaluated_on: date
    seal: str


@dataclass(frozen=True)
class Rule:
    id: RuleId
    path: Path
    title: str
    severity: Severity
    family: Family
    scope: Scope
    question: Question
    flag_examples: tuple[FlagExample, ...]
    clean_examples: tuple[CleanExample, ...]
    guidance: str
    sources: frozenset[CommentId]
    near_misses: frozenset[CommentId]
    needs_repo_search: bool
    repo_search_hint: str | None
    # Overrides the severity's floor, such as for reuse rules whose citation
    # check supplies the precision.
    min_precision: float | None
    calibration: Calibration | None

    @property
    def shown_comments(self) -> frozenset[CommentId]:
        """Comments whose code Jev sees as an example. Eval never scores this rule on them."""
        flags = {
            example.quote.comment for example in self.flag_examples if example.quote
        }
        cleans = {example.comment for example in self.clean_examples if example.comment}
        return frozenset(flags | cleans)


@dataclass(frozen=True)
class WindowSettings:
    max_lines: int


@dataclass(frozen=True)
class Budget:
    max_windows: int
    max_llm_windows: int
    max_findings_per_rule: int
    max_annotations: int
    patch_context_chars: int
    max_search_matches: int


@dataclass(frozen=True)
class LlmSettings:
    model: str
    reasoning_effort: str
    timeout_seconds: float
    # Patterns no finding may raise. The LLM prompt carries them verbatim.
    never_flag: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationPolicy:
    # Two-sided confidence of the Wilson interval on tune-split precision.
    confidence: float
    min_positives: int
    report_percent: int
    min_precision: Mapping[Severity, float]


@dataclass(frozen=True)
class EvalSettings:
    # Sampled negatives per rule, so eval cost stays flat as the corpus grows.
    max_negatives_per_rule: int


@dataclass(frozen=True)
class Prices:
    """USD per 1M tokens, for the cost line of the run summary."""

    jev_input: float
    llm_input: float
    llm_output: float


@dataclass(frozen=True)
class Settings:
    # A pinned version, never "jev-latest". It is part of every seal.
    jev_model: str
    ignore: tuple[str, ...]
    window: WindowSettings
    budget: Budget
    llm: LlmSettings
    calibration: CalibrationPolicy
    eval: EvalSettings
    prices: Prices

    def ignores(self, path: str) -> bool:
        return _matches(path, self.ignore)


@dataclass(frozen=True)
class Registry:
    settings: Settings
    # Sorted by id.
    rules: tuple[Rule, ...]

    def in_scope(self, path: str) -> tuple[Rule, ...]:
        if self.settings.ignores(path):
            return ()
        return tuple(rule for rule in self.rules if rule.scope.covers(path))

    def only(self, rule_ids: Iterable[RuleId]) -> "Registry":
        wanted = set(rule_ids)
        unknown = wanted - {rule.id for rule in self.rules}
        if unknown:
            raise RegistryError(f"unknown rule ids: {', '.join(sorted(unknown))}")
        return replace(self, rules=tuple(r for r in self.rules if r.id in wanted))


def precision_floor(rule: Rule, settings: Settings) -> float:
    """The Wilson lower bound of tune precision a rule needs to post."""
    if rule.min_precision is not None:
        return rule.min_precision
    return settings.calibration.min_precision[rule.severity]


def load_registry(directory: Path = RULES_DIR) -> Registry:
    settings_file = directory / SETTINGS_FILE
    settings = _parse_settings(_Table(_read(settings_file), str(settings_file)))
    rules = tuple(
        _parse_rule(file)
        for file in sorted(directory.glob("*.toml"))
        if file.name != SETTINGS_FILE
    )
    return Registry(settings, rules)


def write_calibration(rule: Rule, calibration: Calibration | None) -> bool:
    """Replace, add or remove the trailing `[calibration]` table of a rule file.

    Returns True when the file changed. A result that differs from the stored
    one only in `evaluated_on` leaves the file alone.
    """
    text = rule.path.read_text()
    body = _strip_calibration(text)
    current = _render_calibration(rule.calibration) if rule.calibration else ""
    new = _render_calibration(calibration) if calibration else ""
    if _without_date(current) == _without_date(new):
        return False
    rule.path.write_text(f"{body}\n\n{new}" if new else f"{body}\n")
    return True


def _strip_calibration(text: str) -> str:
    match = _CALIBRATION_HEADER.search(text)
    return (text[: match.start()] if match else text).rstrip()


def _without_date(rendered: str) -> str:
    return "\n".join(
        row for row in rendered.splitlines() if not row.startswith("evaluated_on")
    )


def _render_calibration(calibration: Calibration) -> str:
    return (
        "[calibration]\n"
        f"threshold = {calibration.threshold:.4f}\n"
        f"precision = {_float(calibration.precision)}\n"
        f"recall = {_float(calibration.recall)}\n"
        f"positives = {calibration.positives}\n"
        f"negatives = {calibration.negatives}\n"
        f"tune_precision_lower = {_float(calibration.tune_precision_lower)}\n"
        f'jev_model = "{calibration.jev_model}"\n'
        f"evaluated_on = {calibration.evaluated_on.isoformat()}\n"
        f'seal = "{calibration.seal}"\n'
    )


def _float(value: float) -> str:
    return "nan" if value != value else f"{value:.4f}"


def _read(file: Path) -> dict[str, object]:
    try:
        return tomllib.loads(file.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RegistryError(f"{file}: {error}") from error


class _Table:
    """Typed reads from one parsed TOML table. Every key must be read once."""

    def __init__(self, raw: Mapping[str, object], where: str) -> None:
        self._raw: Mapping[str, object] = raw
        self._where: str = where
        self._read: set[str] = set()

    def has(self, key: str) -> bool:
        return key in self._raw

    def _get(self, key: str) -> object:
        self._read.add(key)
        if key not in self._raw:
            raise RegistryError(f"{self._where}: missing key `{key}`")
        return self._raw[key]

    def error(self, message: str) -> RegistryError:
        return RegistryError(f"{self._where}: {message}")

    def _fail(self, key: str, expected: str) -> RegistryError:
        return self.error(f"`{key}` must be {expected}")

    def text(self, key: str) -> str:
        value = self._get(key)
        if not isinstance(value, str) or not value.strip():
            raise self._fail(key, "a non-empty string")
        return value.strip()

    def code(self, key: str) -> str:
        """Like `text`, but keeps the indentation of the first line."""
        value = self._get(key)
        if not isinstance(value, str) or not value.strip():
            raise self._fail(key, "a non-empty string")
        return value.strip("\n").rstrip()

    def choice[E: StrEnum](self, key: str, enum: type[E]) -> E:
        value = self.text(key)
        try:
            return enum(value)
        except ValueError as error:
            choices = " | ".join(member.value for member in enum)
            raise self._fail(key, choices) from error

    def optional_text(self, key: str) -> str | None:
        return self.text(key) if self.has(key) else None

    def integer(self, key: str) -> int:
        value = self._get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise self._fail(key, "an integer")
        return value

    def number(self, key: str) -> float:
        value = self._get(key)
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise self._fail(key, "a number")
        return float(value)

    def flag(self, key: str) -> bool:
        value = self._get(key)
        if not isinstance(value, bool):
            raise self._fail(key, "true or false")
        return value

    def day(self, key: str) -> date:
        value = self._get(key)
        if not isinstance(value, date):
            raise self._fail(key, "a date")
        return value

    def texts(
        self, key: str, default: tuple[str, ...] | None = None
    ) -> tuple[str, ...]:
        if default is not None and not self.has(key):
            return default
        value = self._get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise self._fail(key, "a list of non-empty strings")
        return tuple(item.strip() for item in value)

    def comment_ids(self, key: str) -> frozenset[CommentId]:
        value = self._get(key) if self.has(key) else []
        if not isinstance(value, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in value
        ):
            raise self._fail(key, "a list of review comment ids")
        return frozenset(CommentId(item) for item in value)

    def table(self, key: str) -> "_Table":
        value = self._get(key)
        if not isinstance(value, dict):
            raise self._fail(key, "a table")
        return _Table(value, f"{self._where} [{key}]")

    def tables(self, key: str) -> list["_Table"]:
        value = self._get(key) if self.has(key) else []
        if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
            raise self._fail(key, "an array of tables")
        return [_Table(item, f"{self._where} [[{key}]]") for item in value]

    def done[T](self, result: T) -> T:
        unknown = set(self._raw) - self._read
        if unknown:
            raise RegistryError(
                f"{self._where}: unknown keys {', '.join(sorted(unknown))}"
            )
        return result


def _parse_settings(table: _Table) -> Settings:
    window = table.table("window")
    budget = table.table("budget")
    llm = table.table("llm")
    calibration = table.table("calibration")
    min_precision = calibration.table("min_precision")
    evaluation = table.table("eval")
    prices = table.table("prices")
    settings = Settings(
        jev_model=table.text("jev_model"),
        ignore=table.texts("ignore"),
        window=window.done(WindowSettings(max_lines=window.integer("max_lines"))),
        budget=budget.done(
            Budget(
                max_windows=budget.integer("max_windows"),
                max_llm_windows=budget.integer("max_llm_windows"),
                max_findings_per_rule=budget.integer("max_findings_per_rule"),
                max_annotations=budget.integer("max_annotations"),
                patch_context_chars=budget.integer("patch_context_chars"),
                max_search_matches=budget.integer("max_search_matches"),
            )
        ),
        llm=llm.done(
            LlmSettings(
                model=llm.text("model"),
                reasoning_effort=llm.text("reasoning_effort"),
                timeout_seconds=llm.number("timeout_seconds"),
                never_flag=llm.texts("never_flag", default=()),
            )
        ),
        calibration=calibration.done(
            CalibrationPolicy(
                confidence=calibration.number("confidence"),
                min_positives=calibration.integer("min_positives"),
                report_percent=calibration.integer("report_percent"),
                min_precision=min_precision.done(
                    {
                        severity: min_precision.number(severity.value)
                        for severity in Severity
                    }
                ),
            )
        ),
        eval=evaluation.done(
            EvalSettings(
                max_negatives_per_rule=evaluation.integer("max_negatives_per_rule")
            )
        ),
        prices=prices.done(
            Prices(
                jev_input=prices.number("jev_input"),
                llm_input=prices.number("llm_input"),
                llm_output=prices.number("llm_output"),
            )
        ),
    )
    if settings.budget.max_annotations > MAX_ANNOTATIONS_PER_REQUEST:
        raise table.error(
            f"`budget.max_annotations` must be at most {MAX_ANNOTATIONS_PER_REQUEST}"
        )
    if settings.jev_model.endswith("latest"):
        raise table.error("`jev_model` must pin a version")
    return table.done(settings)


def _parse_rule(file: Path) -> Rule:
    rule_id = file.stem
    if not _RULE_ID.match(rule_id):
        raise RegistryError(f"{file}: the file name must be a kebab-case rule id")
    text = file.read_text()
    calibration_header = _CALIBRATION_HEADER.search(text)
    if calibration_header and _TABLE_HEADER.search(text, calibration_header.end()):
        raise RegistryError(f"{file}: [calibration] must be the last table")
    table = _Table(_read(file), str(file))
    scope = table.table("scope")
    question = table.table("question")
    needs_repo_search = table.flag("needs_repo_search")
    rule = Rule(
        id=RuleId(rule_id),
        path=file,
        title=table.text("title"),
        severity=table.choice("severity", Severity),
        family=table.choice("family", Family),
        scope=scope.done(
            Scope(paths=scope.texts("paths"), exclude=scope.texts("exclude", ()))
        ),
        question=question.done(
            Question(
                instructions=question.text("instructions"),
                true_what=question.text("true_what"),
                true_not_for=question.texts("true_not_for", ()),
                false_what=question.text("false_what"),
                false_not_for=question.texts("false_not_for", ()),
            )
        ),
        flag_examples=tuple(_parse_flag(item) for item in table.tables("flag")),
        clean_examples=tuple(_parse_clean(item) for item in table.tables("clean")),
        guidance=table.text("guidance"),
        sources=table.comment_ids("sources"),
        near_misses=table.comment_ids("near_misses"),
        needs_repo_search=needs_repo_search,
        repo_search_hint=table.optional_text("repo_search_hint"),
        min_precision=(
            table.number("min_precision") if table.has("min_precision") else None
        ),
        calibration=(
            _parse_calibration(table.table("calibration"))
            if table.has("calibration")
            else None
        ),
    )
    if not rule.sources:
        raise RegistryError(f"{file}: `sources` must cite at least one comment")
    if rule.min_precision is not None and not 0 <= rule.min_precision <= 1:
        raise table.error("`min_precision` must be between 0 and 1")
    if rule.repo_search_hint and not needs_repo_search:
        raise RegistryError(f"{file}: `repo_search_hint` needs `needs_repo_search`")
    return table.done(rule)


def _parse_flag(table: _Table) -> FlagExample:
    code = table.code("code")
    quote = (
        Quote(CommentId(table.integer("comment")), table.text("said"))
        if table.has("comment") or table.has("said")
        else None
    )
    return table.done(FlagExample(code, quote))


def _parse_clean(table: _Table) -> CleanExample:
    code = table.code("code")
    comment = CommentId(table.integer("comment")) if table.has("comment") else None
    return table.done(CleanExample(code, comment))


def _parse_calibration(table: _Table) -> Calibration:
    return table.done(
        Calibration(
            threshold=table.number("threshold"),
            precision=table.number("precision"),
            recall=table.number("recall"),
            positives=table.integer("positives"),
            negatives=table.integer("negatives"),
            tune_precision_lower=table.number("tune_precision_lower"),
            jev_model=table.text("jev_model"),
            evaluated_on=table.day("evaluated_on"),
            seal=table.text("seal"),
        )
    )
