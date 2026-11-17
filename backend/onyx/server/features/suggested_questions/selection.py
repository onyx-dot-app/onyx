from collections import Counter, defaultdict

from sqlalchemy.orm import Session

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
    SQ_FEW_DOCUMENTS,
    SQ_MAX_LINE_REPEATS,
    SQ_MAX_LINK_RATIO,
    SQ_MAX_WORD_OVERLAP,
    SQ_MIN_CHUNK_CHARS,
    SQ_MIN_LETTER_RATIO,
    SQ_PRIVATE_DOCS_PER_USER,
    SQ_SHARED_DOCS,
    SQ_TRIAGE_CHUNKS_MAX,
)
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    QuestionKind,
    TriagedChunk,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def choose_documents(
    db_session: Session,
    people: list[User],
    exclude_ids: set[str],
    prefer_private: bool = False,
) -> list[CandidateDocument]:
    """Pick the documents a run writes questions about: the newest ones everyone
    can see, and for each person the newest ones only they (or a few people)
    can see, topped up with their uploads when those fall short. Each person
    has their own query, so a large shared connector cannot crowd out their
    documents. Access uses the same rules as search."""
    shared = [
        CandidateDocument(document_id=document_id, kind=QuestionKind.DOCUMENT)
        for document_id in get_newest_public_document_ids(
            db_session, SQ_SHARED_DOCS, exclude_ids
        )
    ]

    private: list[CandidateDocument] = []
    # A Playground company has at most 5 people, so these are a few small
    # queries per run. One query per person keeps them easy to read and debug;
    # combining them into one statement or running them in parallel would not
    # be worth the extra code.
    for person in people:
        granted = [
            CandidateDocument(document_id=document_id, kind=QuestionKind.DOCUMENT)
            for document_id in get_newest_private_document_ids(
                db_session,
                user_email=person.email,
                external_group_ids=get_user_external_group_ids(db_session, person),
                user_id=person.id,
                prior_emails=person.prior_emails,
                limit=SQ_PRIVATE_DOCS_PER_USER,
                exclude_ids=exclude_ids,
            )
        ]
        # Uploads only fill the bucket when connector documents fall short.
        missing = SQ_PRIVATE_DOCS_PER_USER - len(granted)
        uploads = (
            [
                CandidateDocument(document_id=user_file_id, kind=QuestionKind.USER_FILE)
                for user_file_id in get_recent_user_file_ids(
                    db_session, person.id, missing, exclude_ids
                )
            ]
            if missing > 0
            else []
        )
        private.extend([*granted, *uploads])

    ordered = [*private, *shared] if prefer_private else [*shared, *private]
    seen: set[str] = set()
    candidates = []
    for candidate in ordered:
        if candidate.document_id not in seen:
            seen.add(candidate.document_id)
            candidates.append(candidate)
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
    so a long document cannot take the share of a short one. One index call."""
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
        if len(kept) >= SQ_TRIAGE_CHUNKS_MAX:
            break
    return kept


def looks_useful(content: str) -> bool:
    """Cheap rules for chunks with nothing to ask about: too short, mostly
    links, numbers or code, or the same line again and again (footers,
    tables of contents). Everything else goes to triage."""
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


def best_chunks_per_document(triaged: list[TriagedChunk]) -> list[TriagedChunk]:
    """The best chunks of each document after triage: one per document, or two
    when fewer than SQ_FEW_DOCUMENTS documents are left, so a small company
    still gets enough passages. Usable score first, a concrete fact breaks
    ties."""
    by_document: dict[str, list[TriagedChunk]] = defaultdict(list)
    for item in triaged:
        by_document[item.chunk.document_id].append(item)
    per_document = 2 if len(by_document) < SQ_FEW_DOCUMENTS else 1
    return [
        best
        for items in by_document.values()
        # Rounded, so close usable scores tie and a concrete fact decides.
        for best in sorted(
            items, key=lambda item: (round(item.usable), item.has_fact), reverse=True
        )[:per_document]
    ]
