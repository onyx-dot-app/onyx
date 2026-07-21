"""Shared, request-scoped state for the internal search tool and its
paginate companion.

One ``SearchToolTurnState`` is created per chat request (per model) and handed
to both ``SearchTool`` and ``PaginateSearchResultsTool``. It holds:

- The incrementing ``search_query_id`` counter (starts at 1 each turn).
- One ``SearchEntry`` per executed search: the query specs that ran against
  the document index, the full RRF-merged section list (including everything
  beyond the window returned to the LLM), and whatever prefetched data a
  deeper OpenSearch re-query needs when a requested page runs past the cache.
- The once-per-turn automatic semantic rephrase.

Everything lives in memory only for the duration of the request — the state is
garbage collected with the tool instances once the answer is returned. Tools
run in parallel threads within one LLM cycle, so all mutation happens under
locks.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from pydantic import BaseModel

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import InferenceSection
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ExecutedQuerySpec(BaseModel):
    """A single query as it was executed against the document index.

    Slack/federated retrievals are deliberately excluded — pagination only
    re-queries the document index.
    """

    query: str
    weight: float
    # None -> default hybrid search; 0.0 -> pure keyword (BM25), no embedding.
    hybrid_alpha: float | None


@dataclass
class SearchEntry:
    """Cached state for one internal_search call (one search_query_id)."""

    query_specs: list[ExecutedQuerySpec]
    # Full RRF-merged + chunk-merged section list, NOT truncated to the window
    # returned to the LLM. Pagination windows slice into this list.
    merged_sections: list[InferenceSection]
    # (document_id, chunk_id) for every chunk in merged_sections; dedup for
    # deeper fetches.
    cached_chunk_ids: set[tuple[str, int]]
    # Per-query retrieval depth so far; the next fallback fetch starts here.
    per_query_fetch_depth: int
    # Query used for the LLM relevance-selection/expansion steps on each page.
    user_query: str
    # Everything a deeper re-query of the same search needs.
    effective_filters: BaseFilters | None
    acl_filters: list[str] | None
    embedding_model: EmbeddingModel
    project_id_filter: int | None
    persona_id_filter: int | None
    bypass_acl: bool
    # Latched once deeper fetches can't yield anything new.
    exhausted: bool = False
    # Already-rendered pages, for idempotent re-serving (stable citations).
    page_responses: dict[int, ToolResponse] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class SearchToolTurnState:
    """Thread-safe container shared by the search + paginate tools for one
    chat request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self._entries: dict[int, SearchEntry] = {}
        # Separate lock so a slow rephrase LLM call doesn't block id
        # registration from parallel search calls.
        self._rephrase_lock = threading.Lock()
        self._rephrase_computed = False
        self._rephrase: str | None = None

    def register(self, entry: SearchEntry) -> int:
        """Store a new search entry and return its search_query_id."""
        with self._lock:
            search_query_id = self._next_id
            self._next_id += 1
            self._entries[search_query_id] = entry
            return search_query_id

    def get(self, search_query_id: int) -> SearchEntry | None:
        with self._lock:
            return self._entries.get(search_query_id)

    def get_or_compute_rephrase(
        self, compute_fn: Callable[[], str | None]
    ) -> str | None:
        """Run the automatic semantic rephrase at most once per turn.

        Parallel first-cycle search calls all get the same result; failures are
        cached as None so a broken rephrase isn't retried on every call.
        """
        if self._rephrase_computed:
            return self._rephrase
        with self._rephrase_lock:
            if self._rephrase_computed:
                return self._rephrase
            try:
                self._rephrase = compute_fn()
            except Exception:
                logger.exception("Automatic semantic rephrase failed")
                self._rephrase = None
            self._rephrase_computed = True
            return self._rephrase
