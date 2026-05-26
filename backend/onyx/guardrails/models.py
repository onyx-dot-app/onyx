"""Typed contracts for guardrail decisions."""
from enum import StrEnum

from pydantic import BaseModel


class GuardAction(StrEnum):
    """How the runtime should treat a request/response after a guard check."""

    PASS = "pass"
    BLOCK = "block"
    REDACT = "redact"
    LOG_ONLY = "log_only"


class GuardStage(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class GuardDecision(BaseModel):
    """Structured outcome of a single guardrail evaluation.

    ``snippet_hash`` is a sha256 of the matched substring (never the raw text)
    so audit trails / tracing spans don't leak user content.

    ``redacted_text`` is populated only when ``action == REDACT`` — caller swaps
    this in for the original input/output before further processing.
    """

    stage: GuardStage
    action: GuardAction
    rule: str
    reason: str
    snippet_hash: str | None = None
    redacted_text: str | None = None
