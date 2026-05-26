"""Output-side guardrail: runs after generation, before final emission.

Decision priority (first match wins):
- secret_leakage → REDACT (silently strip secrets that slipped into output)
- citation_required → BLOCK (caller may regenerate once; on second failure pass)
"""
from onyx.guardrails.models import GuardAction
from onyx.guardrails.models import GuardDecision
from onyx.guardrails.models import GuardStage
from onyx.guardrails.regex_rules import count_citation_markers
from onyx.guardrails.regex_rules import MIN_OUTPUT_LEN_FOR_CITATION_CHECK
from onyx.guardrails.regex_rules import redact_secrets
from onyx.utils.logger import setup_logger

logger = setup_logger()


def check_output(text: str, kb_tool_used: bool) -> GuardDecision:
    """Evaluate generated output before it leaves the runtime.

    ``kb_tool_used`` is True iff this turn called a knowledge-base search tool;
    only then do we enforce ``citation_required``. Web-only / chitchat turns
    don't need ``[n]`` markers.
    """
    if not text:
        return GuardDecision(
            stage=GuardStage.OUTPUT,
            action=GuardAction.PASS,
            rule="empty",
            reason="empty output",
        )

    # ── 1. secret_leakage: redact any secret that slipped through ────────────
    redacted_text, matched_rules = redact_secrets(text)
    if matched_rules:
        decision = GuardDecision(
            stage=GuardStage.OUTPUT,
            action=GuardAction.REDACT,
            rule="secret_leakage",
            reason=f"redacted secrets: {','.join(matched_rules)}",
            redacted_text=redacted_text,
        )
        logger.warning(
            "Guardrail REDACT (output): rule=secret_leakage patterns=%s",
            ",".join(matched_rules),
        )
        return decision

    # ── 2. citation_required: only enforce on substantive KB-grounded turns ─
    if (
        kb_tool_used
        and len(text) > MIN_OUTPUT_LEN_FOR_CITATION_CHECK
        and count_citation_markers(text) == 0
    ):
        decision = GuardDecision(
            stage=GuardStage.OUTPUT,
            action=GuardAction.BLOCK,
            rule="citation_required",
            reason=(
                "KB search tool was used and output is substantive, but no "
                "[n]-style citation markers were emitted"
            ),
        )
        logger.warning("Guardrail BLOCK (output): rule=citation_required")
        return decision

    return GuardDecision(
        stage=GuardStage.OUTPUT,
        action=GuardAction.PASS,
        rule="ok",
        reason="no guardrail matched",
    )
