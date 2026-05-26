"""Compiled regex catalogs + low-level matchers for input/output guards.

Patterns are deliberately tight to limit false positives. Keep the catalogs
short — broad patterns generate noise that erodes trust in guard decisions.
"""
import hashlib
import re

# ── Configuration ─────────────────────────────────────────────────────────────
MAX_INPUT_CHARS = 50_000  # block obviously oversized prompts pre-LLM
MIN_OUTPUT_LEN_FOR_CITATION_CHECK = 200  # short answers can skip citation
REDACTED_PLACEHOLDER = "[REDACTED:{rule}]"


# ── Secret patterns (block on input, redact on output) ────────────────────────
# Tight patterns — word boundaries + minimum length to avoid matching things
# like "sk-someShortVar" in code samples.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_kv": re.compile(
        r"(?i)\baws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{20,}\b"
    ),
    "github_pat": re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "tavily_dev_key": re.compile(r"\btvly-(?:dev-)?[A-Za-z0-9]{20,}\b"),
    "langfuse_key": re.compile(r"\b(?:pk|sk)-lf-[A-Za-z0-9-]{30,}\b"),
    "pem_block": re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    "jwt": re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
}


# ── Prompt-injection patterns (log_only on input) ─────────────────────────────
# Conservative set — observed in real attacks + Vietnamese variants for this
# project. Logged not blocked so we can iterate before tightening.
PROMPT_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_previous": re.compile(
        r"\b(ignore|disregard)\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)\b",
        re.IGNORECASE,
    ),
    "reveal_system_prompt": re.compile(
        r"(?i)(reveal|show|print|leak|output)\s+(your\s+)?(system\s+prompt|hidden\s+instructions?|the\s+instructions)",
    ),
    "role_override": re.compile(
        r"(?i)\byou\s+are\s+now\s+(a\s+|an\s+)?(?!the\b)\w+",
    ),
    "vi_bypass": re.compile(
        r"(?i)bỏ qua (mọi |tất cả )?(hướng dẫn|chỉ dẫn|lệnh)\s+(trước|cũ|cấu hình)",
    ),
}


CITATION_MARKER_PATTERN = re.compile(r"\[\d+\]")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash(text: str) -> str:
    """SHA256 of a matched substring, truncated to 16 hex chars for trace ids."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def detect_secrets(text: str) -> list[tuple[str, str]]:
    """Return ``[(rule_name, snippet_hash), ...]`` for each secret pattern that
    matched anywhere in the text. Snippet itself is never returned to caller.
    """
    matches: list[tuple[str, str]] = []
    for rule, pattern in SECRET_PATTERNS.items():
        m = pattern.search(text)
        if m:
            matches.append((rule, _hash(m.group(0))))
    return matches


def detect_prompt_injection(text: str) -> list[str]:
    """Return list of matched prompt-injection rule names."""
    return [
        rule for rule, pat in PROMPT_INJECTION_PATTERNS.items() if pat.search(text)
    ]


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Replace every secret match with ``[REDACTED:<rule>]``. Returns
    ``(new_text, [rule_names_matched])``.
    """
    new_text = text
    matched_rules: list[str] = []
    for rule, pattern in SECRET_PATTERNS.items():
        if pattern.search(new_text):
            matched_rules.append(rule)
            new_text = pattern.sub(REDACTED_PLACEHOLDER.format(rule=rule), new_text)
    return new_text, matched_rules


def count_citation_markers(text: str) -> int:
    """Count ``[\\d+]``-style citation tokens in an output."""
    return len(CITATION_MARKER_PATTERN.findall(text))
