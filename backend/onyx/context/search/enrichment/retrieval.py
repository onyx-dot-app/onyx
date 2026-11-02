"""The lane that retrieves a withheld source and clears it with its provider.

Split in two on purpose. Resolving which sources are live, and with whose
credentials, needs a database session; running the search does not. The
chat path resolves ahead of time and hands the result down, as it already
does for federated search.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.credentials import pair_secrets
from onyx.connectors.event_inbox.sources import load_event_sources
from onyx.context.search.enrichment.models import EnrichmentContext
from onyx.context.search.enrichment.registry import (
    enrichment_source_types,
    get_enrichment_filter,
)
from onyx.db.connector_credential_pair import get_active_cc_pairs_for_source
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_enrichment_contexts(
    db_session: Session,
    user: User | None,
    source_types: Sequence[DocumentSource] | None,
) -> list[EnrichmentContext]:
    """The withheld sources this user can be served right now.

    Anonymous users get none: the provider answers about a named user, and
    the anonymous identity is one shared address, not a person.
    """
    if user is None or user.is_anonymous or not user.email:
        return []

    load_event_sources()

    contexts: list[EnrichmentContext] = []
    for source in enrichment_source_types():
        # An explicit source selection scopes this lane as it scopes the
        # default one.
        if source_types is not None and source not in source_types:
            continue
        permission_filter = get_enrichment_filter(source)
        if permission_filter is None:
            continue
        pairs = get_active_cc_pairs_for_source(db_session, source)
        if not pairs:
            continue
        # One pair per source, as the event inbox resolves it: a second
        # account needs a routing key neither side declares yet.
        contexts.append(
            EnrichmentContext(
                source=source,
                permission_filter=permission_filter,
                user_email=user.email,
                secrets=pair_secrets(pairs[0]),
            )
        )
    return contexts
