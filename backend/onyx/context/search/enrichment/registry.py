"""Sources that are indexed but kept out of the default search lane.

A normal connector's documents are what internal search is for. A few are
not: the provider, not Onyx, decides who may read each one, and the answer
can change between the moment a document is indexed and the moment somebody
searches. Such a source is indexed as usual and then withheld — the default
lane excludes it, and a lane of its own retrieves it and asks the provider
about every chunk before any of it reaches a user.

The exclusion is read from this registry alone, with no database call, so a
source stays out of the default lane even when the enrichment lane cannot
run.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from onyx.configs.constants import WITHHELD_FROM_DEFAULT_SEARCH, DocumentSource
from onyx.context.search.models import InferenceChunk


# runtime_checkable so `EnrichmentContext` can hold one as a Pydantic field.
@runtime_checkable
class ChunkPermissionFilter(Protocol):
    def __call__(
        self,
        user_email: str,
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],
    ) -> list[InferenceChunk]:
        """The chunks this user may read, asked of the provider.

        `secrets` is the pair's decrypted credential JSON. Raise to drop the
        whole lane: a filter that cannot reach its provider has proved
        nothing, and returning the chunks unfiltered would publish them.

        The verdict must depend on the document, not on the chunk: the
        caller remembers it per document id and does not ask twice in one
        search.
        """


_FILTERS: dict[DocumentSource, ChunkPermissionFilter] = {}


def register_enrichment_source(
    source: DocumentSource, permission_filter: ChunkPermissionFilter
) -> None:
    """Withhold one source from the default lane. Import-time.

    Refuses a duplicate rather than replacing it: the second registration
    would decide who can read the first's documents.
    """
    existing = _FILTERS.get(source)
    if existing is not None and existing is not permission_filter:
        raise ValueError(
            f"{source.value} is already registered as an enrichment source."
        )
    _FILTERS[source] = permission_filter


def unregister_enrichment_source(source: DocumentSource) -> None:
    """Give up a source. Unknown sources are ignored.

    Registration is an import side effect, so the only callers are the ones
    that undo it: the loader rolling back a failed import, and tests.
    """
    _FILTERS.pop(source, None)


def get_enrichment_filter(source: DocumentSource) -> ChunkPermissionFilter | None:
    return _FILTERS.get(source)


def registered_enrichment_sources() -> set[DocumentSource]:
    """Only the sources that registered a filter.

    Distinct from `enrichment_source_types`, which adds the static floor: a
    caller asking what has been registered must not be told about a source
    that merely must not be searched.
    """
    return set(_FILTERS)


def enrichment_source_types() -> list[DocumentSource]:
    """What the default lane must not return.

    The static floor is unioned in, so a source stays withheld even when its
    implementation is not installed or failed to import. Resolving a lane
    for one is a separate question: `get_enrichment_filter` answers None and
    the caller skips it.
    """
    return sorted(
        set(_FILTERS) | WITHHELD_FROM_DEFAULT_SEARCH, key=lambda source: source.value
    )
