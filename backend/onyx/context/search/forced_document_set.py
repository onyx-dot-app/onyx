"""Operator-forced document-set search scope (self-hosted Search UI only).

When ``FORCED_DOCUMENT_SET_NAMES`` is set, the Onyx Search UI is hard-restricted to
those document sets. The vector index stores document set NAMES, so the configured
names are used directly — no resolution needed. Disabled under MULTI_TENANT.

Fail-closed by construction: a name that doesn't exist matches no chunk, so the
scope can only ever narrow results. The names are verified against the DB and any
missing one is logged as an error (the operator's signal that a name is a typo or
was renamed).
"""

from sqlalchemy.orm import Session

from onyx.configs.app_configs import FORCED_DOCUMENT_SET_NAMES
from onyx.db.document_set import get_document_sets_by_name
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def get_forced_document_set_names(db_session: Session | None) -> list[str] | None:
    """The operator-forced document set names, or None when the feature is disabled
    (multitenant, or ``FORCED_DOCUMENT_SET_NAMES`` empty).

    Verifies the names exist (when a session is available) and logs an error for any
    that don't — a missing name simply matches nothing, so the scope stays safe.
    """
    if MULTI_TENANT or not FORCED_DOCUMENT_SET_NAMES:
        return None

    if db_session is not None:
        existing = {
            ds.name
            for ds in get_document_sets_by_name(db_session, FORCED_DOCUMENT_SET_NAMES)
        }
        missing = [name for name in FORCED_DOCUMENT_SET_NAMES if name not in existing]
        if missing:
            logger.error(
                "FORCED_DOCUMENT_SET_NAMES references document sets that do not exist: "
                "%s. Search returns nothing for those names.",
                missing,
            )

    return FORCED_DOCUMENT_SET_NAMES
