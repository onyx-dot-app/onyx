"""Linear-time regex compilation backed by Google RE2 (``google-re2``).

RE2 matches in time linear in the input length and does not backtrack, so it is
immune to catastrophic-backtracking (ReDoS) blowups. Use :func:`compile_linear`
for any pattern that runs over untrusted or LLM-generated text — most notably
the streaming citation processor, whose patterns previously caused a CPU-pinning
ReDoS on adversarial model output.

Patterns passed here must use only RE2-supported syntax: no backreferences
(``\\1``), lookahead/lookbehind (``(?=...)``, ``(?<=...)``), atomic groups, or
possessive quantifiers. Normal groups, named groups, character classes, anchors,
and greedy/lazy quantifiers are all supported.

If ``google-re2`` is unavailable (e.g. a platform without a prebuilt wheel), this
falls back to the stdlib ``re`` engine so the application still runs, and logs a
warning once so the active engine is observable. Under the fallback the patterns
are NOT backtracking-safe, so callers must still avoid pathological patterns.
"""

import re
from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()

try:
    import re2 as _re2  # google-re2

    USING_RE2 = True
except ImportError:  # pragma: no cover - depends on platform wheel availability
    _re2 = None  # ty: ignore[invalid-assignment]
    USING_RE2 = False

_fallback_warned = False


def _warn_fallback_once() -> None:
    """Log the stdlib-fallback warning the first time it's needed.

    Deferred out of the module-level ImportError handler so we never emit logs as
    an import-time side effect (which could fire before logging is configured).
    """
    global _fallback_warned
    if not _fallback_warned:
        _fallback_warned = True
        logger.warning(
            "google-re2 is not available; falling back to the stdlib 're' engine "
            "for linear-time patterns. ReDoS protection is reduced for untrusted "
            "input."
        )


def compile_linear(pattern: str) -> Any:
    """Compile ``pattern`` with RE2 when available, else the stdlib ``re`` engine.

    Returns a compiled pattern object exposing the standard
    ``search``/``match``/``finditer``/``sub`` API. Typed as ``Any`` because
    ``google-re2`` ships no type stubs and its Pattern/Match objects are not the
    stdlib ``re`` types.
    """
    if _re2 is not None:
        return _re2.compile(pattern)
    _warn_fallback_once()
    return re.compile(pattern)
