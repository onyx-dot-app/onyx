from collections import Counter, defaultdict
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.access.access import get_censoring_enabled_sources
from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.suggested_questions import (
    get_newest_private_document_ids,
    get_newest_public_document_ids,
    get_recent_user_file_ids,
)
from onyx.document_index.factory import get_default_document_index
from onyx.server.features.suggested_questions.config import (
    SQ_CHUNKS_PER_DOC,
    SQ_FETCH_CHUNKS_PER_DOC,
    SQ_MAX_LINE_REPEATS,
    SQ_MAX_LINK_RATIO,
    SQ_MAX_WORD_OVERLAP,
    SQ_MIN_CHUNK_CHARS,
    SQ_MIN_LETTER_RATIO,
    SQ_PRIVATE_DOCS_PER_USER,
    SQ_SHARED_DOCS,
)
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    QuestionKind,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class NothingSearchableYet(Exception):
    """The chosen documents have no chunks in the search index yet."""


def choose_documents(
    db_session: Session,
    people: list[User],
    shared_exclude_ids: set[str],
    private_exclude_ids: Mapping[UUID, set[str]],
    include_shared: bool = True,
) -> list[CandidateDocument]:
    """Pick the documents a run writes questions about: the newest ones everyone
    can see, and for each person the newest ones only they (or a few people)
    can see, topped up with their uploads when those fall short. Each person
    has their own query, so a large shared connector cannot crowd out their
    documents. Access uses the same rules as search.

    Each private candidate records the people whose bucket chose it, so its
    question goes on their private shelves. A document already on a shelf is
    skipped for that shelf only. A top-up passes include_shared=False: the
    shared shelf is filled by pool runs."""
    censored_sources = get_censoring_enabled_sources()
    shared = (
        [
            CandidateDocument(document_id=document_id, kind=QuestionKind.DOCUMENT)
            for document_id in get_newest_public_document_ids(
                db_session, SQ_SHARED_DOCS, shared_exclude_ids, censored_sources
            )
        ]
        if include_shared
        else []
    )

    # The private query leaves out documents everyone can see, so a document is
    # never both shared and private. A group document can be in several
    # people's buckets: one candidate, several owners.
    owners: dict[str, list[UUID]] = defaultdict(list)
    kinds: dict[str, QuestionKind] = {}
    # A Playground company has at most 5 people, so these are a few small
    # queries per run. One query per person keeps them easy to read and debug;
    # combining them into one statement or running them in parallel would not
    # be worth the extra code.
    for person in people:
        exclude_ids = private_exclude_ids.get(person.id, set())
        granted = get_newest_private_document_ids(
            db_session,
            user_email=person.email,
            external_group_ids=get_user_external_group_ids(db_session, person),
            user_id=person.id,
            prior_emails=person.prior_emails,
            limit=SQ_PRIVATE_DOCS_PER_USER,
            exclude_ids=exclude_ids,
            censored_sources=censored_sources,
        )
        # Uploads only fill the bucket when connector documents fall short.
        missing = SQ_PRIVATE_DOCS_PER_USER - len(granted)
        uploads = (
            get_recent_user_file_ids(db_session, person.id, missing, exclude_ids)
            if missing > 0
            else []
        )
        for document_id in granted:
            kinds.setdefault(document_id, QuestionKind.DOCUMENT)
            owners[document_id].append(person.id)
        for user_file_id in uploads:
            kinds[user_file_id] = QuestionKind.USER_FILE
            owners[user_file_id].append(person.id)

    private = [
        CandidateDocument(
            document_id=document_id, kind=kinds[document_id], owner_ids=owner_ids
        )
        for document_id, owner_ids in owners.items()
    ]
    candidates = [*shared, *private]
    logger.info(
        "Suggested questions: chose %d documents (%d shared, %d private) for %d people",
        len(candidates),
        len(shared),
        len(private),
        len(people),
    )
    return candidates


def fetch_chunks(
    db_session: Session, candidates: list[CandidateDocument], tenant_id: str
) -> list[InferenceChunk]:
    """The first chunks of each chosen document, with obvious junk dropped and
    at most SQ_CHUNKS_PER_DOC per document. Each document gets its own range,
    so a long document cannot take the share of a short one. One index call.
    Raises NothingSearchableYet when the index returns no chunks at all."""
    if not candidates:
        return []
    document_index = get_default_document_index(
        get_current_search_settings(db_session), None
    )
    chunks = document_index.leading_chunks_retrieval(
        filters=IndexFilters(
            # No user filter: access is checked per person when they open the chat.
            access_control_list=None,
            tenant_id=tenant_id,
            attached_document_ids=[candidate.document_id for candidate in candidates],
        ),
        max_chunk_index=SQ_FETCH_CHUNKS_PER_DOC - 1,
    )
    if not chunks:
        # Chunks become searchable at the index's next refresh, about a
        # second after indexing. A run started sooner reads nothing.
        raise NothingSearchableYet(f"No chunks for {len(candidates)} documents")
    kept = keep_useful_chunks(chunks)
    logger.info(
        "Suggested questions: read %d chunks of %d documents, kept %d after the junk rules",
        len(chunks),
        len(candidates),
        len(kept),
    )
    return kept


def keep_useful_chunks(chunks: list[InferenceChunk]) -> list[InferenceChunk]:
    kept: list[InferenceChunk] = []
    kept_words: list[set[str]] = []
    per_document: Counter[str] = Counter()
    for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id):
        if per_document[chunk.document_id] >= SQ_CHUNKS_PER_DOC:
            continue
        if not looks_useful(chunk.content):
            continue
        words = set(chunk.content.lower().split())
        if any(
            len(words & other) > SQ_MAX_WORD_OVERLAP * len(words)
            for other in kept_words
        ):
            continue
        kept.append(chunk)
        kept_words.append(words)
        per_document[chunk.document_id] += 1
    return kept


def looks_useful(content: str) -> bool:
    """Cheap rules for chunks with nothing to ask about: too short, mostly
    links, numbers or code, or the same line again and again (footers,
    tables of contents). Everything else goes to the writing call."""
    text = content.strip()
    if len(text) < SQ_MIN_CHUNK_CHARS:
        return False
    letters = sum(char.isalpha() or char.isspace() for char in text)
    if letters < SQ_MIN_LETTER_RATIO * len(text):
        return False
    words = text.split()
    links = sum(word.startswith(("http://", "https://", "www.")) for word in words)
    if links > SQ_MAX_LINK_RATIO * len(words):
        return False
    line_counts = Counter(line.strip() for line in text.splitlines() if line.strip())
    return max(line_counts.values(), default=0) <= SQ_MAX_LINE_REPEATS
