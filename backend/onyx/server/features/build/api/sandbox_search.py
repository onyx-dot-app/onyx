"""Sandbox-callable search endpoint that mirrors the regular Onyx search tool.

Wired up via the ``company_search`` skill: from inside a Craft sandbox, the
agent runs ``company_search "<query>"``, which curls this endpoint with the
session's bearer token and prints the LLM-facing markdown to stdout. The
endpoint instantiates ``SearchTool`` exactly the way the chat path does and
returns its rich + LLM-facing responses, so chat search and Craft search stay
in lockstep.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from queue import Queue

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import PersonaSearchInfo
from onyx.context.search.models import SearchDocsResponse
from onyx.db.engine.sql_engine import get_session
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_default_llm
from onyx.server.features.build.api.sandbox_auth import require_sandbox_session_token
from onyx.server.features.build.api.sandbox_auth import SandboxRequestContext
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.constants import MAX_CHUNKS_FOR_RELEVANCE
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Sandbox callers don't share the cookie-based auth dependency tree of the
# main /api/build router, so they live on their own sub-router with the
# bearer-token dependency.
sandbox_router = APIRouter(
    prefix="/build/sandbox",
    dependencies=[Depends(require_sandbox_session_token)],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

# Match Onyx's chat-path search defaults so Craft search returns the same
# number of citations a user would see in the regular search experience.
_DEFAULT_NUM_HITS = 10
_MAX_NUM_HITS = 25


class SandboxSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1024)
    limit: int | None = Field(default=None, ge=1, le=_MAX_NUM_HITS)
    source_filters: list[str] | None = None
    time_cutoff_days: int | None = Field(default=None, ge=1, le=365 * 5)


class SandboxSearchDoc(BaseModel):
    citation_id: int
    document_id: str
    chunk_ind: int
    title: str
    blurb: str
    link: str | None
    source_type: str
    score: float | None
    updated_at: str | None


class SandboxSearchResponse(BaseModel):
    results: list[SandboxSearchDoc]
    llm_facing_text: str
    citation_mapping: dict[int, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_source_filters(
    raw_sources: list[str] | None,
) -> list[DocumentSource] | None:
    if not raw_sources:
        return None

    parsed: list[DocumentSource] = []
    for raw in raw_sources:
        normalized = raw.strip().lower()
        if not normalized:
            continue
        try:
            parsed.append(DocumentSource(normalized))
        except ValueError:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Unknown source filter: {raw!r}",
            )
    return parsed or None


def _build_user_selected_filters(
    request: SandboxSearchRequest,
) -> BaseFilters | None:
    sources = _resolve_source_filters(request.source_filters)
    time_cutoff: datetime | None = None
    if request.time_cutoff_days is not None:
        time_cutoff = datetime.now(tz=timezone.utc) - timedelta(
            days=request.time_cutoff_days
        )
    if sources is None and time_cutoff is None:
        return None
    return BaseFilters(source_type=sources, time_cutoff=time_cutoff)


def _build_sink_emitter() -> Emitter:
    """Emitter that drops every packet on the floor.

    Sandbox search is a synchronous request/response — we don't have a
    streaming consumer to deliver packets to, so we hand SearchTool a
    queue/event pair that nobody drains.
    """
    drained_queue: Queue[tuple[int, Packet | Exception | object]] = Queue()
    return Emitter(merged_queue=drained_queue, model_idx=0)


def _format_results(tool_response: ToolResponse) -> SandboxSearchResponse:
    rich = tool_response.rich_response
    if not isinstance(rich, SearchDocsResponse):
        # SearchTool guarantees a SearchDocsResponse; this is just a typed
        # safety net so a future refactor can't silently change the shape.
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "SearchTool returned an unexpected rich response type",
        )

    citation_mapping = rich.citation_mapping
    doc_id_to_citation = {doc_id: cid for cid, doc_id in citation_mapping.items()}

    results: list[SandboxSearchDoc] = []
    for doc in rich.search_docs:
        citation_id = doc_id_to_citation.get(doc.document_id)
        if citation_id is None:
            # Doc didn't make it into the LLM-facing trim; skip it so the
            # caller doesn't get phantom citations.
            continue
        results.append(
            SandboxSearchDoc(
                citation_id=citation_id,
                document_id=doc.document_id,
                chunk_ind=doc.chunk_ind,
                title=doc.semantic_identifier,
                blurb=doc.blurb,
                link=doc.link,
                source_type=doc.source_type.value,
                score=doc.score,
                updated_at=doc.updated_at.isoformat() if doc.updated_at else None,
            )
        )

    results.sort(key=lambda r: r.citation_id)

    return SandboxSearchResponse(
        results=results,
        llm_facing_text=tool_response.llm_facing_response,
        citation_mapping=citation_mapping,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@sandbox_router.post("/search")
def sandbox_search(
    request: SandboxSearchRequest,
    context: SandboxRequestContext = Depends(require_sandbox_session_token),
    db_session: Session = Depends(get_session),
) -> SandboxSearchResponse:
    """Run a permissioned hybrid search on behalf of the session's user.

    Constructs ``SearchTool`` with the same shape as the chat path
    (PersonaSearchInfo empty, default document index, default LLM, no project/
    persona scoping) and calls ``.run([query])``. The LLM-facing response
    string and citation mapping are returned verbatim so the agent gets the
    same retrieval quality a chat user gets. Approval/rate-limiting is the
    job of upstream layers — this endpoint only enforces auth and tenancy.
    """
    user = context.user
    build_session = context.build_session

    user_selected_filters = _build_user_selected_filters(request)

    # Source-of-truth for retrieval shape: mirror tool_constructor._build_search_tool.
    persona_search_info = PersonaSearchInfo(
        document_set_names=[],
        search_start_date=None,
        attached_document_ids=[],
        hierarchy_node_ids=[],
    )

    search_settings = get_current_search_settings(db_session)
    if search_settings is None:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "No search settings configured",
        )

    document_index = get_default_document_index(search_settings, None, db_session)

    try:
        llm = get_default_llm()
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, str(e))

    search_tool = SearchTool(
        # tool_id is a DB column on Tool; sandbox search is not a registered
        # persona tool, so we use a sentinel of 0. The id is only used for
        # output routing in the chat UI, which sandbox search bypasses.
        tool_id=0,
        emitter=_build_sink_emitter(),
        user=user,
        persona_search_info=persona_search_info,
        llm=llm,
        document_index=document_index,
        user_selected_filters=user_selected_filters,
        project_id_filter=None,
        persona_id_filter=None,
        bypass_acl=False,
        slack_context=None,
        enable_slack_search=True,
    )

    num_hits = request.limit or _DEFAULT_NUM_HITS

    override_kwargs = SearchToolOverrideKwargs(
        starting_citation_num=1,
        original_query=request.query,
        num_hits=num_hits,
        # Match chat: cap chunks fed to the LLM-facing string at the same
        # value Onyx uses for relevance trimming.
        max_llm_chunks=max(num_hits, MAX_CHUNKS_FOR_RELEVANCE),
    )

    placement = Placement(turn_index=0)

    try:
        tool_response = search_tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            queries=[request.query],
        )
    except RuntimeError as e:
        # SearchTool raises RuntimeError for "no search settings" / pipeline
        # failures. Surface as a gateway error so the skill exits non-zero.
        logger.exception(f"Sandbox search failed for session {build_session.id}: {e}")
        raise OnyxError(OnyxErrorCode.BAD_GATEWAY, f"Search failed: {e}")

    response = _format_results(tool_response)

    logger.info(
        "sandbox_search session=%s user=%s query_len=%d results=%d",
        build_session.id,
        user.id,
        len(request.query),
        len(response.results),
    )

    return response


__all__ = ["sandbox_router", "sandbox_search"]
