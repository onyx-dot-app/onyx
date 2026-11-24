"""Deterministic synthetic corpus for the docprocessing benchmark.

A `CorpusSpec` fixes every byte of every document, so the index that one run
writes can be compared with the index of another run. The text is made of common
English words, which tokenize at about the rate of prose. It is not real
content: use it to compare builds, not to predict a customer's corpus.
"""

import math
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import BasicExpertInfo, Document, TextSection

# A request with this marker fails in the mock model server when the run asks
# for poisoned documents.
POISON_MARKER = "BENCHPOISONEMBED"

_BASE_UPDATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_SECTION_TARGET_CHARS = 8_000
_MAX_SECTIONS = 200
_SENTENCE_POOL_SIZE = 4_096
_TEAMS = ("engineering", "sales", "support", "finance", "legal", "product")

_WORDS = (
    "the of and to in is that for it as was with be by on not he this are or his "
    "from at which but have an had they you were their one all we can her has "
    "there been if more when will would who so no out up into than them only "
    "time some could these two may then do first any my now such like our over "
    "man me even most made after also did many before must through years where "
    "much your way well down should because each just those people how too "
    "little state good very make world still own see men work long get here "
    "between both life being under never day same another know while last might "
    "us great old year off come since against go came right used take three "
    "customer report system service account project request update review team "
    "meeting process release contract invoice policy access deploy ticket issue "
    "schedule budget design server database product support security network "
    "document change quarter revenue feature platform migration pipeline "
    "analysis summary proposal deadline approval incident response capacity "
    "performance requirement integration configuration environment production"
).split()


class CorpusProfile(str, Enum):
    SMALL = "small"
    MIXED = "mixed"
    LARGE = "large"
    PATHOLOGICAL = "pathological"


_DEFAULT_DOCS: dict[CorpusProfile, int] = {
    CorpusProfile.SMALL: 3_200,
    CorpusProfile.MIXED: 1_600,
    CorpusProfile.LARGE: 48,
    CorpusProfile.PATHOLOGICAL: 16,
}


class CorpusSpec(BaseModel):
    profile: CorpusProfile = CorpusProfile.MIXED
    docs: int | None = Field(default=None, ge=1)
    seed: int = 7
    # Documents that the mock model server refuses to embed.
    poison_docs: int = Field(default=0, ge=0)
    # Fixed size for every document. Overrides the profile's distribution.
    doc_chars: int | None = Field(default=None, ge=1)

    @property
    def num_docs(self) -> int:
        return self.docs or _DEFAULT_DOCS[self.profile]

    @property
    def corpus_id(self) -> str:
        parts = [self.profile.value, str(self.num_docs), f"s{self.seed}"]
        if self.poison_docs:
            parts.append(f"p{self.poison_docs}")
        if self.doc_chars:
            parts.append(f"c{self.doc_chars}")
        return "-".join(parts)


class DocSpec(BaseModel):
    index: int
    doc_id: str
    chars: int
    # True when revision 1 of the corpus holds new content for this document.
    changes_in_revision_1: bool
    poisoned: bool


def _doc_chars(spec: CorpusSpec, rng: random.Random) -> int:
    if spec.doc_chars:
        return spec.doc_chars
    if spec.profile == CorpusProfile.SMALL:
        return rng.randint(1_000, 5_000)
    if spec.profile == CorpusProfile.MIXED:
        # Long tail: median 6k characters, a few documents in the megabytes.
        return int(min(max(rng.lognormvariate(math.log(6_000), 1.5), 300), 2_000_000))
    if spec.profile == CorpusProfile.LARGE:
        return rng.randint(1_000_000, 8_000_000)
    return 20_000_000


def _poisoned_indexes(spec: CorpusSpec) -> set[int]:
    if not spec.poison_docs:
        return set()
    step = max(spec.num_docs // spec.poison_docs, 1)
    return set(list(range(step // 2, spec.num_docs, step))[: spec.poison_docs])


def iter_doc_specs(spec: CorpusSpec) -> Iterator[DocSpec]:
    """The documents of the corpus, without their text."""
    rng = random.Random(f"sizes:{spec.seed}:{spec.profile.value}")  # noqa: S311
    poisoned = _poisoned_indexes(spec)
    for index in range(spec.num_docs):
        yield DocSpec(
            index=index,
            doc_id=f"bench://{spec.corpus_id}/{index:07d}",
            chars=_doc_chars(spec, rng),
            changes_in_revision_1=index % 10 == 0 and index not in poisoned,
            poisoned=index in poisoned,
        )


def _sentence_pool(seed: int) -> list[str]:
    rng = random.Random(f"pool:{seed}")  # noqa: S311
    pool: list[str] = []
    for _ in range(_SENTENCE_POOL_SIZE):
        words: list[str] = rng.choices(_WORDS, k=rng.randint(6, 22))
        if rng.random() < 0.3:
            words.insert(rng.randrange(len(words)), str(rng.randint(1, 99_999)))
        pool.append(" ".join(words).capitalize() + ".")
    return pool


def _text(rng: random.Random, pool: list[str], chars: int) -> str:
    average = 80
    parts: list[str] = []
    length = 0
    while length < chars:
        sentences = rng.choices(pool, k=max((chars - length) // average + 1, 1))
        for start in range(0, len(sentences), 5):
            paragraph = " ".join(sentences[start : start + 5]) + "\n\n"
            parts.append(paragraph)
            length += len(paragraph)
    return "".join(parts)[:chars].rstrip()


class CorpusGenerator:
    def __init__(self, spec: CorpusSpec) -> None:
        self.spec = spec
        self._pool = _sentence_pool(spec.seed)

    def build(self, doc: DocSpec, revision: int) -> Document:
        """Revision 0 is the base corpus. Revision 1 changes one document in ten,
        to half the size, so each changed document ends with fewer chunks."""
        changed = revision > 0 and doc.changes_in_revision_1
        applied_revision = revision if changed else 0
        chars = max(doc.chars // 2, 200) if changed else doc.chars
        rng = random.Random(  # noqa: S311
            f"doc:{self.spec.seed}:{doc.index}:{applied_revision}"
        )

        num_sections = min(max(chars // _SECTION_TARGET_CHARS, 1), _MAX_SECTIONS)
        section_chars = chars // num_sections
        sections: list[TextSection] = []
        for section_index in range(num_sections):
            text = _text(rng, self._pool, section_chars)
            if doc.poisoned and section_index == 0:
                text = f"{POISON_MARKER} {text}"
            sections.append(
                TextSection(
                    text=text,
                    link=f"https://bench.invalid/{doc.index}#s{section_index}",
                )
            )

        owner = doc.index % 50
        return Document(
            id=doc.doc_id,
            sections=sections,
            source=DocumentSource.MOCK_CONNECTOR,
            semantic_identifier=f"Bench document {doc.index}",
            title=f"Bench document {doc.index}",
            metadata={
                "team": _TEAMS[doc.index % len(_TEAMS)],
                "tags": [f"tag-{doc.index % 13}", f"tag-{doc.index % 7}"],
            },
            doc_updated_at=_BASE_UPDATED_AT
            + timedelta(minutes=doc.index, days=applied_revision),
            primary_owners=[
                BasicExpertInfo(
                    display_name=f"Owner {owner}", email=f"owner{owner}@bench.invalid"
                )
            ],
        )

    def iter_documents(self, revision: int) -> Iterator[Document]:
        for doc in iter_doc_specs(self.spec):
            yield self.build(doc, revision)
