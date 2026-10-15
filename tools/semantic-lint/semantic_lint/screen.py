"""Ask Jev how likely each in-scope rule applies to each window.

`screen()` is the one function CI and eval share. One request per window
carries one noul per in-scope rule. Jev bills the state once per request plus
about 100 tokens per question, and latency stays flat as questions grow.

This module also owns the seal, because only it knows what the ask contains.
A stored threshold is valid only while the question, scope, window size and
model it was measured with are unchanged.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from itertools import batched
from typing import Any, Literal, NotRequired, TypedDict

from semantic_lint.diff import Window
from semantic_lint.registry import (
    Registry,
    Rule,
    RuleId,
    Settings,
    precision_floor,
)

__all__ = [
    "Hit",
    "Jev",
    "Mode",
    "Score",
    "Screening",
    "Usage",
    "active_threshold",
    "question_fingerprint",
    "rule_mode",
    "screen",
    "seal",
]

JEV_URL: str = "https://api.typesafe.ai/v1/systemone"
# Bump when the state or the question payload changes shape. Every seal
# includes it, so a bump deactivates every rule until eval reruns.
STATE_FORMAT: int = 1
# A guard, not a documented API limit. More questions go in a second request.
MAX_QUESTIONS_PER_REQUEST: int = 50
PARALLEL_REQUESTS: int = 16
JEV_TIMEOUT_SECONDS: float = 60.0
# TypeSafe documents 429 and 529 as retryable. The 5xx codes are gateway blips.
RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS: int = 5


@dataclass(frozen=True)
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.requests + other.requests,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.seconds + other.seconds,
        )


@dataclass(frozen=True)
class Score:
    window_id: str
    rule_id: RuleId
    p: float


@dataclass(frozen=True)
class Hit:
    window: Window
    rule: Rule
    p: float
    threshold: float

    @property
    def margin(self) -> float:
        return self.p - self.threshold


class Mode(StrEnum):
    # Sealed calibration that meets the precision policy. Hits go to the LLM.
    LIVE = "live"
    # Sealed calibration below the policy. Screened, counted, never posted.
    SHADOW = "shadow"
    # No calibration, or a broken seal. Not screened.
    INACTIVE = "inactive"


@dataclass(frozen=True)
class Screening:
    windows: tuple[Window, ...]
    scores: tuple[Score, ...]
    # `seconds` is wall time for the whole screening.
    usage: Usage

    def hits(self, registry: Registry) -> list[Hit]:
        """Scores at or above their rule's active threshold, largest margin first."""
        rules = {rule.id: rule for rule in registry.rules}
        windows = {window.id: window for window in self.windows}
        hits: list[Hit] = []
        for score in self.scores:
            rule = rules[score.rule_id]
            threshold = active_threshold(rule, registry.settings)
            if threshold is not None and score.p >= threshold:
                hits.append(Hit(windows[score.window_id], rule, score.p, threshold))
        return sorted(hits, key=lambda hit: hit.margin, reverse=True)


class _Criterion(TypedDict):
    what: str
    not_for: NotRequired[list[str]]
    examples: NotRequired[list[str]]


class _Criteria(TypedDict):
    true: _Criterion
    false: _Criterion


class _NoulQuestion(TypedDict):
    type: Literal["noul"]
    instructions: str
    criteria: _Criteria


def _criterion(
    what: str, not_for: Sequence[str], examples: Sequence[str]
) -> _Criterion:
    criterion: _Criterion = {"what": what}
    if not_for:
        criterion["not_for"] = list(not_for)
    if examples:
        criterion["examples"] = list(examples)
    return criterion


def _question(rule: Rule) -> _NoulQuestion:
    question = rule.question
    return {
        "type": "noul",
        "instructions": question.instructions,
        "criteria": {
            "true": _criterion(
                question.true_what,
                question.true_not_for,
                [example.code for example in rule.flag_examples],
            ),
            "false": _criterion(
                question.false_what,
                question.false_not_for,
                [example.code for example in rule.clean_examples],
            ),
        },
    }


def question_fingerprint(rule: Rule) -> str:
    return _digest({"state_format": STATE_FORMAT, "question": _question(rule)})


def seal(rule: Rule, threshold: float, settings: Settings) -> str:
    return "sha256:" + _digest(
        {
            "state_format": STATE_FORMAT,
            "jev_model": settings.jev_model,
            "window_max_lines": settings.window.max_lines,
            "threshold": f"{threshold:.4f}",
            "scope": {"paths": rule.scope.paths, "exclude": rule.scope.exclude},
            "question": _question(rule),
        }
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def active_threshold(rule: Rule, settings: Settings) -> float | None:
    """The stored threshold, or None when there is none or its seal is broken."""
    calibration = rule.calibration
    if calibration is None:
        return None
    if calibration.seal != seal(rule, calibration.threshold, settings):
        return None
    return calibration.threshold


def rule_mode(rule: Rule, settings: Settings) -> Mode:
    if rule.calibration is None or active_threshold(rule, settings) is None:
        return Mode.INACTIVE
    floor = precision_floor(rule, settings)
    return Mode.LIVE if rule.calibration.tune_precision_lower >= floor else Mode.SHADOW


class Jev:
    """The TypeSafe System One client. Tests subclass it and override `ask`."""

    def __init__(self, api_key: str) -> None:
        self._api_key: str = api_key

    def ask(
        self, model: str, window: Window, rules: Sequence[Rule]
    ) -> tuple[dict[RuleId, float], Usage]:
        started = time.monotonic()
        response = self._post(
            {
                "model": model,
                "state": {"file": window.path, "diff": window.render()},
                "questions": {rule.id: _question(rule) for rule in rules},
            }
        )
        answers = response["answers"]
        probabilities: dict[RuleId, float] = {}
        for rule in rules:
            answer = answers.get(rule.id) or {}
            if answer.get("type") != "noul" or not isinstance(
                answer.get("noul"), int | float
            ):
                raise ValueError(f"Jev returned no noul for {rule.id}: {answer}")
            probabilities[rule.id] = float(answer["noul"])
        usage = Usage(
            requests=1,
            input_tokens=int(response["usage"]["input_tokens"]),
            output_tokens=int(response["usage"]["output_tokens"]),
            seconds=time.monotonic() - started,
        )
        return probabilities, usage

    def _post(self, body: object) -> Any:
        request = urllib.request.Request(  # noqa: S310
            JEV_URL,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        for attempt in range(MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(  # noqa: S310
                    request, timeout=JEV_TIMEOUT_SECONDS
                ) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                    detail = error.read()[:500].decode(errors="replace")
                    raise RuntimeError(
                        f"Jev returned {error.code}: {detail}"
                    ) from error
                time.sleep(2**attempt)
            except (urllib.error.URLError, TimeoutError):
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")


def screen(windows: Sequence[Window], registry: Registry, jev: Jev) -> Screening:
    """Score every (window, rule) pair where the rule's scope covers the window.

    The first failed request fails the screening.
    """
    started = time.monotonic()
    model = registry.settings.jev_model
    jobs = [
        (window, chunk)
        for window in windows
        for chunk in batched(
            registry.in_scope(window.path), MAX_QUESTIONS_PER_REQUEST, strict=False
        )
    ]
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        answers = list(pool.map(lambda job: jev.ask(model, *job), jobs))
    scores = tuple(
        Score(window.id, rule_id, p)
        for (window, _), (probabilities, _) in zip(jobs, answers, strict=True)
        for rule_id, p in probabilities.items()
    )
    usage = sum((usage for _, usage in answers), Usage())
    return Screening(
        windows=tuple(windows),
        scores=scores,
        usage=Usage(
            usage.requests,
            usage.input_tokens,
            usage.output_tokens,
            time.monotonic() - started,
        ),
    )
