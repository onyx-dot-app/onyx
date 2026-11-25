"""A whole suggested-questions run against real Postgres, OpenSearch and the
cache. Only the models are stubbed: the writing LLM and the query embedder
(CI has no model server).

Each test document gets its own one-hot vector, and the fake query embedder
points each test question at the vector of the document it is about, so hybrid
search ranks that document first. An off-topic question about the parking
document points at three decoy documents instead and must fail the search
test.
"""

import json
import re
import sys
from collections.abc import Callable, Generator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from celery.exceptions import Retry
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.background.celery.tasks.suggested_questions import tasks
from onyx.configs.constants import KV_SUGGESTED_QUESTIONS_POOL_KEY
from onyx.db.document import (
    get_cc_pair_ids_for_documents,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.models import Document as DbDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.indexing.models import ChunkEmbedding
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.suggested_questions import scheduling, verification
from onyx.server.features.suggested_questions.models import RefreshReason
from onyx.server.features.suggested_questions.store import load_pool, pool_lock
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    make_chunk,
    make_indexing_metadata,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

# Name, one-hot index of its vector, text. The decoys share index 0. Each text
# is long enough for the junk rules and shares few words with the others.
DOCS = [
    (
        "remote",
        1,
        "Employees may work from another country for up to 30 working days per calendar year. Requests longer than ten days in a row need approval from People Operations through the travel form, at least two weeks before the trip starts. Tax rules differ by country, so check the guide first. Managers confirm cover for the team while the person is away.",
    ),
    (
        "expense",
        2,
        "Every employee gets a yearly home office budget of 500 dollars, renewed each January. Buy a desk, chair, monitor or headset and submit the receipt in the expense tool within thirty days. Unused budget does not roll over, and finance pays claims with the next salary run. Laptops are not part of this budget; IT provides them instead.",
    ),
    (
        "deploy",
        3,
        "Production deploys on Fridays need approval from the on-call engineering lead. Open the release checklist, confirm the rollback plan and post in the deploys channel before merging. Hotfixes for an active incident may skip the Friday approval but still need a reviewed pull request. Deploys are frozen during the last week of each quarter entirely.",
    ),
    (
        "parking",
        5,
        "Staff parking permits are issued by facilities for one quarter at a time. Apply in the permit portal before the first Monday of the quarter, choose the level you want, and attach your licence plate. Electric vehicle bays on level two have chargers that may be used for four hours at most per day, so move the car once it is charged.",
    ),
    (
        "decoy-a",
        0,
        "Notes about the office kitchen: the coffee machine is descaled every Monday, plants are watered on Thursdays, and the fridge is cleared each Friday afternoon. Label your food with a name and date, and bring mugs back from meeting rooms before leaving for the evening. The dishwasher runs at six, so load it before the cleaners arrive.",
    ),
    (
        "decoy-b",
        0,
        "Book club reading list for the next quarter, chosen by vote in the social channel. October covers a history of the printing press, November a novel set on a lighthouse, and December a collection of short essays about gardening. Meetings happen on the last Wednesday at lunch. New members can join any month and borrow a copy from the shelf.",
    ),
    (
        "decoy-c",
        0,
        "Directions to the office: take the green line to Harbour Street and walk two blocks north. Visitors collect a badge at the front desk on the ground floor. Parking spaces behind the building are shared, so reserve one in the facilities form a day ahead of the visit. Bicycles go in the covered rack beside the loading bay at the back.",
    ),
]
QUESTIONS = {
    "remote": "How many working days can employees work from another country?",
    "expense": "How large is the yearly home office budget?",
    "deploy": "Who approves a production deploy on Fridays?",
}
OFF_TOPIC = "What is the capital city of France?"


@pytest.fixture
def seeded(
    full_deployment_setup: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> Generator[dict[str, Any], None, None]:
    """The documents in Postgres and the default index, and an empty pool."""
    suffix = uuid4().hex[:8]
    ids = {name: f"sq-{name}-{suffix}" for name, _, _ in DOCS}
    search_settings = get_current_search_settings(db_session)
    dim = search_settings.final_embedding_dim
    pair = make_cc_pair(db_session)
    index = get_default_document_index(search_settings, None)
    # Clean up whatever setup created, even if setup fails part way.
    try:
        _clear_pool()
        now = datetime.now(UTC)
        for name, _, _ in DOCS:
            db_session.add(
                DbDocument(
                    id=ids[name], semantic_id=ids[name], chunk_count=1, last_synced=now
                )
            )
        db_session.commit()
        upsert_document_by_connector_credential_pair(
            db_session, pair.connector_id, pair.credential_id, list(ids.values())
        )
        access = get_access_for_documents(list(ids.values()), db_session)
        cc_pair_ids = get_cc_pair_ids_for_documents(db_session, list(ids.values()))
        for name, slot, text in DOCS:
            doc_id = ids[name]
            vector = [1.0 if i == slot else 0.0 for i in range(dim)]
            chunk = make_chunk(doc_id, content=text)
            chunk = chunk.model_copy(
                update={
                    # The title the writing prompt shows.
                    "source_document": chunk.source_document.model_copy(
                        update={"semantic_identifier": doc_id}
                    ),
                    "access": access[doc_id],
                    "cc_pair_ids": cc_pair_ids.get(doc_id),
                    "embeddings": ChunkEmbedding(
                        full_embedding=vector, mini_chunk_embeddings=[]
                    ),
                }
            )
            index.index(
                chunks=[chunk],
                indexing_metadata=make_indexing_metadata([doc_id], [0], [1]),
            )
        OpenSearchIndexClient(index_name=search_settings.index_name).refresh_index()
        yield {"ids": ids, "dim": dim}
    finally:
        # Each step runs even if an earlier one fails; failures are reported.
        steps: list[Callable[[], object]] = [_clear_pool]
        steps += [lambda d=doc_id: index.delete(d) for doc_id in ids.values()]
        steps.append(lambda: cleanup_cc_pair(db_session, pair))
        errors = []
        for step in steps:
            try:
                step()
            except Exception as e:
                errors.append(e)
        if errors:
            raise ExceptionGroup("suggested-questions test cleanup failed", errors)


def _clear_pool() -> None:
    # Only a missing pool is fine; any other error must stop the test.
    with suppress(KvKeyNotFoundError):
        get_kv_store().delete(KV_SUGGESTED_QUESTIONS_POOL_KEY)


@pytest.fixture
def models(seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the writing LLM and the query embedder."""
    ids, dim = seeded["ids"], seeded["dim"]
    name_by_id = {doc_id: name for name, doc_id in ids.items()}
    slot = {name: s for name, s, _ in DOCS}
    state: dict[str, Any] = {"prompts": []}

    def write(request: Any, context: Any) -> Any:  # noqa: ARG001
        prompt = request.messages[-1].text
        state["prompts"].append(prompt)
        written = []
        for number, doc_id in re.findall(r"^\[(\d+)\] (\S+)$", prompt, re.MULTILINE):
            name = name_by_id.get(doc_id)
            if name in QUESTIONS:
                written.append(
                    {
                        "passage": int(number),
                        "question": QUESTIONS[name],
                        "best_for": "hr",
                    }
                )
            elif name == "parking":
                written.append(
                    {"passage": int(number), "question": OFF_TOPIC, "best_for": "any"}
                )
        return MagicMock(text=json.dumps({"questions": written}))

    llm = MagicMock()
    llm.config.model_name = "fake-writer"
    llm.invoke.side_effect = write

    def vector_for(text: str) -> list[float]:
        name = next((n for n, q in QUESTIONS.items() if q == text), None)
        target = slot[name] if name else 0
        return [1.0 if i == target else 0.0 for i in range(dim)]

    embedder = MagicMock(provider_type=None)
    embedder.encode.side_effect = lambda texts, **_kw: [vector_for(t) for t in texts]
    monkeypatch.setattr(
        verification,
        "EmbeddingModel",
        MagicMock(from_db_model=MagicMock(return_value=embedder)),
    )
    # Spy on the real search, to see what each question actually returned.
    real_search = verification._search_everything
    state["searched"] = {}

    def spy(query: str, *args: Any) -> Any:
        chunks = real_search(query, *args)
        state["searched"][query] = [chunk.document_id for chunk in chunks]
        return chunks

    monkeypatch.setattr(verification, "_search_everything", spy)
    monkeypatch.setattr(tasks, "build_writing_llms", lambda: [llm])
    monkeypatch.setattr(tasks, "is_enabled", lambda: True)
    state["llm"] = llm
    return state


def _pool_run() -> None:
    # Typed loosely: celery's stubs do not know the task's keyword arguments.
    task: Any = tasks.generate_suggested_questions_pool
    task.run(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        reason=RefreshReason.FIRST_RUN.value,
    )


def test_a_pool_run_keeps_only_questions_that_find_their_document(
    seeded: dict[str, Any], models: dict[str, Any]
) -> None:
    _pool_run()

    pool = load_pool(refresh_cache=True)
    assert pool is not None
    ids = seeded["ids"]
    by_document = {q.document_id: q for q in pool.questions}
    # Each answerable question found its own document first.
    assert {ids[n] for n in QUESTIONS} <= set(by_document)
    assert all(by_document[ids[n]].search_position == 0 for n in QUESTIONS)
    # The off-topic search ran and found only decoys, so it failed the test.
    top_three = list(dict.fromkeys(models["searched"][OFF_TOPIC]))[:3]
    assert set(top_three) == {ids[n] for n in ("decoy-a", "decoy-b", "decoy-c")}
    assert OFF_TOPIC not in {q.text for q in pool.questions}
    assert len(pool.runs) == 1

    # A second run right after is too soon: no model call.
    calls = models["llm"].invoke.call_count
    _pool_run()
    assert models["llm"].invoke.call_count == calls


def test_a_topup_waits_while_a_pool_run_holds_the_pool(
    models: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    retry = MagicMock(side_effect=Retry())
    task: Any = tasks.generate_suggested_questions_for_user
    monkeypatch.setattr(task, "retry", retry)

    with pool_lock(0), pytest.raises(Retry):
        task.run(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, user_id=str(uuid4()))

    assert retry.call_args.kwargs["countdown"] == tasks.SQ_LOCK_BUSY_RETRY_S
    models["llm"].invoke.assert_not_called()


def test_many_hooks_queue_one_pool_run(
    seeded: dict[str, Any],  # noqa: ARG001 - enough documents for a first run
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        MagicMock(app=client),
    )
    monkeypatch.setattr(scheduling, "IS_PLAYGROUND", True)
    scheduling.release_pool_flag(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        for _ in range(10):
            scheduling.request_pool_refresh(
                POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, RefreshReason.FIRST_RUN
            )
    finally:
        scheduling.release_pool_flag(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    assert client.send_task.call_count == 1
