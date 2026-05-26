"""Input-side guardrail: runs before tool-routing / LLM call.

Decision priority (first match wins): oversized → secret_detection → injection.
"""
from onyx.guardrails.models import GuardAction
from onyx.guardrails.models import GuardDecision
from onyx.guardrails.models import GuardStage
from onyx.guardrails.regex_rules import detect_prompt_injection
from onyx.guardrails.regex_rules import detect_secrets
from onyx.guardrails.regex_rules import MAX_INPUT_CHARS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def check_input(text: str) -> GuardDecision:
    """Evaluate a single user message against all input guards.

    Always returns a ``GuardDecision`` — caller decides what to do based on
    ``action``: BLOCK → raise, REDACT → swap in ``redacted_text``, LOG_ONLY →
    proceed but record, PASS → proceed.
    """
    if not text:
        return GuardDecision(
            stage=GuardStage.INPUT,
            action=GuardAction.PASS,
            rule="empty",
            reason="empty input",
        )

    # ── 1. request_length: hard block on absurdly long inputs ────────────────
    if len(text) > MAX_INPUT_CHARS:
        decision = GuardDecision(
            stage=GuardStage.INPUT,
            action=GuardAction.BLOCK,
            rule="request_length",
            reason=f"input length {len(text)} exceeds limit {MAX_INPUT_CHARS}",
        )
        logger.warning("Guardrail BLOCK (input): %s", decision.reason)
        return decision

    # ── 2. secret_detection: block + log when a real secret is pasted ───────
    secret_matches = detect_secrets(text)
    if secret_matches:
        rule_names = ",".join(r for r, _ in secret_matches)
        snippet_hash = secret_matches[0][1]
        decision = GuardDecision(
            stage=GuardStage.INPUT,
            action=GuardAction.BLOCK,
            rule="secret_detection",
            reason=f"matched secret patterns: {rule_names}",
            snippet_hash=snippet_hash,
        )
        logger.warning(
            "Guardrail BLOCK (input): rule=secret_detection patterns=%s", rule_names
        )
        return decision

    # ── 3. prompt_injection: log_only — don't block, just learn ─────────────
    injection_rules = detect_prompt_injection(text)
    if injection_rules:
        decision = GuardDecision(
            stage=GuardStage.INPUT,
            action=GuardAction.LOG_ONLY,
            rule="prompt_injection",
            reason=f"matched injection patterns: {','.join(injection_rules)}",
        )
        logger.info(
            "Guardrail LOG_ONLY (input): rule=prompt_injection patterns=%s",
            ",".join(injection_rules),
        )
        return decision

    return GuardDecision(
        stage=GuardStage.INPUT,
        action=GuardAction.PASS,
        rule="ok",
        reason="no guardrail matched",
    )
