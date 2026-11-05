"""Sources that are indexed but kept out of the default search lane.

For these the provider, not Onyx, decides who may read each document, and
the answer can change after indexing. A lane of its own retrieves them and
asks the provider about every chunk first.
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

        Raise rather than return the input when the provider cannot answer:
        the caller drops the whole lane, because returning uncleared chunks
        would publish them. The verdict must depend on the document, not the
        chunk, since the caller remembers it per document id.
        """


_FILTERS: dict[DocumentSource, ChunkPermissionFilter] = {}


def register_enrichment_source(
    source: DocumentSource, permission_filter: ChunkPermissionFilter
) -> None:
    """Import-time. A duplicate is refused rather than replaced: the second
    registration would decide who can read the first's documents."""
    existing = _FILTERS.get(source)
    if existing is not None and existing is not permission_filter:
        raise ValueError(
            f"{source.value} is already registered as an enrichment source."
        )
    _FILTERS[source] = permission_filter


def unregister_enrichment_source(source: DocumentSource) -> None:
    _FILTERS.pop(source, None)


def get_enrichment_filter(source: DocumentSource) -> ChunkPermissionFilter | None:
    return _FILTERS.get(source)


def registered_enrichment_sources() -> set[DocumentSource]:
    """The sources that registered a filter, without the static floor."""
    return set(_FILTERS)


def enrichment_source_types() -> list[DocumentSource]:
    """What the default lane must not return.

    The floor is unioned in, so a source stays withheld even when its
    implementation is absent. Serving it is a separate question, which
    `get_enrichment_filter` answers.
    """
    return sorted(
        set(_FILTERS) | WITHHELD_FROM_DEFAULT_SEARCH, key=lambda source: source.value
    )
