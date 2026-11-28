"""The benchmark gates compare digests between runs, so the corpus and the mock
vectors must be the same in every run."""

import hashlib

from scripts.docprocessing_bench.corpus import (
    POISON_MARKER,
    CorpusGenerator,
    CorpusProfile,
    CorpusSpec,
    iter_doc_specs,
)

from tests.integration.mock_services.mock_model_server.server import embed_text


def _digest(spec: CorpusSpec, revision: int) -> str:
    digest = hashlib.sha256()
    for document in CorpusGenerator(spec).iter_documents(revision):
        digest.update(document.model_dump_json().encode())
    return digest.hexdigest()


def test_corpus_bytes_are_pinned() -> None:
    spec = CorpusSpec(profile=CorpusProfile.SMALL, docs=20)
    assert _digest(spec, 0) == _digest(spec, 0)
    # A change to this value changes every golden digest: update golden.json too.
    assert (
        _digest(spec, 0)
        == "787a1be74bf4d9d5a4b237615fffc17b51d9e7905dbeedbeb88066c750c9eec2"
    )


def test_revision_changes_one_document_in_ten_to_half_size() -> None:
    spec = CorpusSpec(profile=CorpusProfile.SMALL, docs=20)
    generator = CorpusGenerator(spec)
    for doc in iter_doc_specs(spec):
        base = generator.build(doc, 0)
        revised = generator.build(doc, 1)
        if doc.changes_in_revision_1:
            assert revised.sections[0].text != base.sections[0].text
            assert len(revised.sections[0].text or "") <= doc.chars // 2
            assert revised.doc_updated_at != base.doc_updated_at
        else:
            assert revised == base


def test_poisoned_documents_carry_the_marker_and_never_change() -> None:
    spec = CorpusSpec(profile=CorpusProfile.SMALL, docs=40, poison_docs=3)
    generator = CorpusGenerator(spec)
    poisoned = [doc for doc in iter_doc_specs(spec) if doc.poisoned]
    assert len(poisoned) == 3
    for doc in iter_doc_specs(spec):
        text = generator.build(doc, 0).sections[0].text or ""
        assert (POISON_MARKER in text) == doc.poisoned
    assert not any(doc.changes_in_revision_1 for doc in poisoned)


def test_corpus_id_separates_corpora() -> None:
    ids = {
        CorpusSpec(profile=CorpusProfile.SMALL).corpus_id,
        CorpusSpec(profile=CorpusProfile.SMALL, docs=10).corpus_id,
        CorpusSpec(profile=CorpusProfile.SMALL, docs=10, seed=8).corpus_id,
        CorpusSpec(profile=CorpusProfile.SMALL, docs=10, poison_docs=1).corpus_id,
        CorpusSpec(profile=CorpusProfile.SMALL, docs=10, doc_chars=500).corpus_id,
        CorpusSpec(profile=CorpusProfile.MIXED, docs=10).corpus_id,
    }
    assert len(ids) == 6


def test_mock_vector_is_a_unit_vector_fixed_by_its_text() -> None:
    vector = embed_text("the same text", 384)
    assert vector == embed_text("the same text", 384)
    assert vector != embed_text("other text", 384)
    assert len(vector) == 384
    assert abs(sum(value * value for value in vector) - 1.0) < 1e-4
    assert vector[:3] == [0.053236, 0.035139, 0.075374]
