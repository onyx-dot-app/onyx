"""reCAPTCHA verification Prometheus metrics.

Tracks every ``verify_captcha_token`` outcome across all three guarded flows
(signup, login, oauth):

  1. Verification volume + pass/fail rate (``onyx_captcha_verifications_total``)
  2. Failure breakdown by reason (``onyx_captcha_failures_total``)
  3. "Flaky" recoveries — an individual that recently failed and then passed
     (``onyx_captcha_flaky_recoveries_total``)

The flaky signal answers "how often does a real user get bounced once and then
get through": a high count relative to total verifications suggests the score
threshold is too aggressive for legitimate traffic. The per-individual state
that drives it lives in Redis (see ``onyx/auth/captcha.py``); only the bounded
``action`` label reaches Prometheus so cardinality stays flat.

Usage:
    from onyx.server.metrics.captcha_metrics import (
        record_captcha_success,
        record_captcha_failure,
        record_captcha_flaky_recovery,
    )
"""

from prometheus_client import Counter

from onyx.utils.logger import setup_logger

logger = setup_logger()

CAPTCHA_VERIFICATIONS = Counter(
    "onyx_captcha_verifications_total",
    "Total reCAPTCHA verification attempts by action and outcome",
    ["action", "outcome"],
)

CAPTCHA_FAILURES = Counter(
    "onyx_captcha_failures_total",
    "reCAPTCHA verification failures broken down by reject reason",
    ["action", "reason"],
)

CAPTCHA_FLAKY_RECOVERIES = Counter(
    "onyx_captcha_flaky_recoveries_total",
    "Verifications that passed after the same individual recently failed (flaky)",
    ["action"],
)


def record_captcha_success(action: str) -> None:
    try:
        CAPTCHA_VERIFICATIONS.labels(action=action, outcome="success").inc()
    except Exception:
        logger.debug("Failed to record captcha success metric", exc_info=True)


def record_captcha_failure(action: str, reason: str) -> None:
    try:
        CAPTCHA_VERIFICATIONS.labels(action=action, outcome="failure").inc()
        CAPTCHA_FAILURES.labels(action=action, reason=reason).inc()
    except Exception:
        logger.debug("Failed to record captcha failure metric", exc_info=True)


def record_captcha_flaky_recovery(action: str) -> None:
    try:
        CAPTCHA_FLAKY_RECOVERIES.labels(action=action).inc()
    except Exception:
        logger.debug("Failed to record captcha flaky recovery metric", exc_info=True)
