"""The measured side of the docprocessing benchmark.

`scripts.benchmark_docprocessing` starts one process per phase, with the
environment that points Onyx at the throwaway database, index and bucket:

    setup   create the database, the index and a cc-pair
    stage   write one pass of the corpus as staged batches, like docfetching
    run     process the staged batches on N threads, like the Celery worker
    verify  read the index and Postgres and report what they hold

Each phase prints one JSON object on its last stdout line.
"""

import argparse
import cProfile
import hashlib
import json
import os
import queue
import resource
import subprocess
import sys
import threading
import time
from datetime import UTC
from pathlib import Path
from typing import Any

import psutil
from opensearchpy import OpenSearch
from opensearchpy.helpers import scan
from pydantic import BaseModel
from sqlalchemy import select

from onyx.background.celery.tasks.docprocessing.heartbeat import start_heartbeat
from onyx.background.celery.tasks.docprocessing.tasks import _docprocessing_task
from onyx.configs.app_configs import (
    FILE_STORE_BACKEND,
    INDEX_BATCH_SIZE,
    OPENSEARCH_ADMIN_PASSWORD,
    OPENSEARCH_ADMIN_USERNAME,
    OPENSEARCH_CA_CERTS,
    OPENSEARCH_HOST,
    OPENSEARCH_REST_API_PORT,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_VERIFY_CERTS,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    REDIS_DB_NUMBER,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    S3_FILE_STORE_BUCKET_NAME,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.index_attempt import (
    create_index_attempt,
    get_index_attempt,
    get_index_attempt_errors,
)
from onyx.db.index_attempt_metrics import get_stage_metrics_for_attempt
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    SearchSettings,
)
from onyx.db.models import Document as DBDocument
from onyx.db.search_settings import (
    get_current_search_settings,
    get_secondary_search_settings,
)
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.opensearch.schema import (
    ACCESS_CONTROL_LIST_FIELD_NAME,
    BLURB_FIELD_NAME,
    CHUNK_INDEX_FIELD_NAME,
    CONTENT_FIELD_NAME,
    CONTENT_VECTOR_FIELD_NAME,
    DOCUMENT_ID_FIELD_NAME,
    DOCUMENT_SETS_FIELD_NAME,
    GLOBAL_BOOST_FIELD_NAME,
    HIDDEN_FIELD_NAME,
    MAX_CHUNK_SIZE_FIELD_NAME,
    METADATA_LIST_FIELD_NAME,
    METADATA_SUFFIX_FIELD_NAME,
    PRIMARY_OWNERS_FIELD_NAME,
    PUBLIC_FIELD_NAME,
    SEMANTIC_IDENTIFIER_FIELD_NAME,
    SOURCE_LINKS_FIELD_NAME,
    SOURCE_TYPE_FIELD_NAME,
    TITLE_FIELD_NAME,
    TITLE_VECTOR_FIELD_NAME,
)
from onyx.file_store.document_batch_storage import get_document_batch_storage
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.models import IndexingSetting
from onyx.redis.redis_pool import get_redis_client
from onyx.setup import setup_document_index, setup_postgres
from scripts.benchmark_shared import flush_redis, recreate_database
from scripts.docprocessing_bench.corpus import (
    CorpusGenerator,
    CorpusSpec,
    iter_doc_specs,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Every throwaway resource carries this prefix. Setup refuses any other name, so
# a wrong environment cannot drop a real database or index.
BENCH_PREFIX = "docproc_bench"
# Bucket names cannot hold an underscore.
BENCH_BUCKET_PREFIX = "docproc-bench"
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
_CELERY_TASK_ID = "docprocessing-bench"
_SAMPLE_INTERVAL_S = 0.1

# The chunk fields that a pipeline change must keep. Timestamps and ids that
# differ between two correct runs are left out.
_DIGEST_FIELDS = (
    DOCUMENT_ID_FIELD_NAME,
    CHUNK_INDEX_FIELD_NAME,
    MAX_CHUNK_SIZE_FIELD_NAME,
    TITLE_FIELD_NAME,
    TITLE_VECTOR_FIELD_NAME,
    CONTENT_FIELD_NAME,
    CONTENT_VECTOR_FIELD_NAME,
    BLURB_FIELD_NAME,
    SOURCE_TYPE_FIELD_NAME,
    METADATA_LIST_FIELD_NAME,
    METADATA_SUFFIX_FIELD_NAME,
    SEMANTIC_IDENTIFIER_FIELD_NAME,
    SOURCE_LINKS_FIELD_NAME,
    PRIMARY_OWNERS_FIELD_NAME,
    PUBLIC_FIELD_NAME,
    ACCESS_CONTROL_LIST_FIELD_NAME,
    DOCUMENT_SETS_FIELD_NAME,
    HIDDEN_FIELD_NAME,
    GLOBAL_BOOST_FIELD_NAME,
)


class SetupResult(BaseModel):
    cc_pair_id: int
    search_settings_id: int
    index_name: str
    model_name: str
    embedding_dim: int
    multipass: bool
    large_chunks: bool
    index_batch_size: int


class StageResult(BaseModel):
    index_attempt_id: int
    batches: int
    docs: int
    chars: int
    stage_seconds: float


class StageMetric(BaseModel):
    stage: str
    events: int
    total_ms: int
    mean_ms: float
    max_ms: int | None


class RunResult(BaseModel):
    threads: int
    batches: int
    failed_batches: int
    batch_errors: list[str]
    elapsed_seconds: float
    cpu_user_seconds: float
    cpu_system_seconds: float
    rss_start_mb: float
    rss_peak_mb: float
    rss_end_mb: float
    cgroup_memory_peak_mb: float | None
    cgroup_memory_limit_mb: float | None
    threads_peak: int
    attempt_status: str
    completed_batches: int
    total_batches: int | None
    total_docs_indexed: int
    new_docs_indexed: int
    total_chunks: int
    error_rows: int
    error_document_ids: list[str]
    heartbeat_counter: int
    stage_metrics: list[StageMetric]
    batch_seconds_p50: float
    batch_seconds_max: float


class VerifyResult(BaseModel):
    index_chunks: int
    index_documents: int
    index_digest: str
    duplicate_chunks: int
    documents_with_gaps: list[str]
    missing_documents: list[str]
    unexpected_documents: list[str]
    chunk_count_mismatches: list[str]
    postgres_documents: int
    postgres_digest: str
    documents_without_content_hash: int
    cc_pair_links: int


def _emit(result: BaseModel) -> None:
    print(result.model_dump_json(), flush=True)


def _require_bench_name(kind: str, name: str) -> None:
    if not name.startswith(BENCH_PREFIX):
        raise RuntimeError(
            f"Refusing to use {kind} '{name}': the name must start with '{BENCH_PREFIX}'."
        )


def _init(pool_size: int) -> None:
    _require_bench_name("database", POSTGRES_DB)
    SqlEngine.set_app_name("docprocessing_bench")
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=8)
    CURRENT_TENANT_ID_CONTEXTVAR.set(_TENANT_ID)


def _opensearch() -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_REST_API_PORT}],
        http_auth=(OPENSEARCH_ADMIN_USERNAME, OPENSEARCH_ADMIN_PASSWORD),
        use_ssl=OPENSEARCH_USE_SSL,
        verify_certs=OPENSEARCH_VERIFY_CERTS,
        ca_certs=OPENSEARCH_CA_CERTS if OPENSEARCH_VERIFY_CERTS else None,
        ssl_show_warn=False,
        timeout=120,
    )


def _require_bench_file_store() -> None:
    # Batch names restart with the database, so a shared store would lose files.
    if FILE_STORE_BACKEND != "s3" or not S3_FILE_STORE_BUCKET_NAME.startswith(
        BENCH_BUCKET_PREFIX
    ):
        raise RuntimeError(
            f"Refusing to use file store '{FILE_STORE_BACKEND}' with bucket "
            f"'{S3_FILE_STORE_BUCKET_NAME}': the benchmark needs the S3 backend "
            f"and a bucket that starts with '{BENCH_BUCKET_PREFIX}'."
        )


def setup(index_name: str) -> SetupResult:
    _require_bench_name("database", POSTGRES_DB)
    _require_bench_name("index", index_name)
    _require_bench_file_store()

    recreate_database(
        POSTGRES_HOST,
        POSTGRES_PORT,
        POSTGRES_USER,
        os.environ.get("POSTGRES_PASSWORD") or "password",
        POSTGRES_DB,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        check=True,
        stdout=sys.stderr,
    )
    flush_redis(REDIS_HOST, REDIS_PORT, REDIS_DB_NUMBER, REDIS_PASSWORD or None)
    _init(pool_size=4)

    client = _opensearch()
    client.indices.delete(index=index_name, ignore_unavailable=True)
    client.close()

    with get_session_with_current_tenant() as db_session:
        # A new database starts on the legacy model with the current default as
        # FUTURE. Startup swaps to it at once when no connector exists. The
        # seeded rows name the indexes of a normal deployment, so rename them
        # first: nothing here may touch an index without the bench prefix.
        next_settings = get_secondary_search_settings(
            db_session
        ) or get_current_search_settings(db_session)
        for row in db_session.scalars(select(SearchSettings)):
            row.index_name = (
                index_name
                if row.id == next_settings.id
                else f"{index_name}_retired_{row.id}"
            )
        db_session.commit()
        check_and_perform_index_swap(db_session=db_session)
        if get_secondary_search_settings(db_session) is not None:
            raise RuntimeError("Bug: FUTURE search settings remain after the swap.")
        setup_postgres(db_session)
        get_default_file_store().initialize()

        search_settings = get_current_search_settings(db_session)
        search_settings.index_name = index_name
        db_session.commit()
        db_session.refresh(search_settings)

        index_setting = IndexingSetting.from_db_model(search_settings)
        if not setup_document_index(
            get_default_document_index(search_settings, None), index_setting
        ):
            raise RuntimeError("The document index did not initialize.")

        connector = Connector(
            name="docprocessing-bench",
            source=DocumentSource.MOCK_CONNECTOR,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={},
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        )
        credential = Credential(
            source=DocumentSource.MOCK_CONNECTOR, credential_json={}
        )
        db_session.add_all([connector, credential])
        db_session.flush()
        pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name="docprocessing-bench",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
            auto_sync_options=None,
        )
        db_session.add(pair)
        db_session.commit()

        multipass = get_multipass_config(search_settings)
        return SetupResult(
            cc_pair_id=pair.id,
            search_settings_id=search_settings.id,
            index_name=index_name,
            model_name=search_settings.model_name,
            embedding_dim=index_setting.final_embedding_dim,
            multipass=multipass.multipass_indexing,
            large_chunks=multipass.enable_large_chunks,
            index_batch_size=INDEX_BATCH_SIZE,
        )


def stage(spec: CorpusSpec, revision: int, cc_pair_id: int) -> StageResult:
    """Stores the corpus as batches of a new attempt, as docfetching does."""
    _init(pool_size=4)
    started = time.monotonic()

    with get_session_with_current_tenant() as db_session:
        attempt_id = create_index_attempt(
            connector_credential_pair_id=cc_pair_id,
            search_settings_id=get_current_search_settings(db_session).id,
            db_session=db_session,
            celery_task_id=_CELERY_TASK_ID,
        )
        attempt = get_index_attempt(db_session, attempt_id)
        if attempt is None:
            raise RuntimeError("Bug: the new index attempt is missing.")
        attempt.status = IndexingStatus.IN_PROGRESS
        db_session.commit()

    storage = get_document_batch_storage(cc_pair_id, attempt_id, is_backfill=False)
    generator = CorpusGenerator(spec)
    batch_num = 0
    docs = 0
    chars = 0
    batch = []
    for document in generator.iter_documents(revision):
        batch.append(document)
        docs += 1
        chars += sum(len(section.text or "") for section in document.sections)
        if len(batch) == INDEX_BATCH_SIZE:
            storage.store_batch(batch_num, batch)
            batch_num += 1
            batch = []
    if batch:
        storage.store_batch(batch_num, batch)
        batch_num += 1

    with get_session_with_current_tenant() as db_session:
        IndexingCoordination.set_total_batches(db_session, attempt_id, batch_num)

    return StageResult(
        index_attempt_id=attempt_id,
        batches=batch_num,
        docs=docs,
        chars=chars,
        stage_seconds=round(time.monotonic() - started, 2),
    )


class _MemorySampler:
    """Tracks the peak RSS and thread count of this process."""

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.peak_rss = self._process.memory_info().rss
        self.peak_threads = self._process.num_threads()

    def _loop(self) -> None:
        while not self._stop.wait(_SAMPLE_INTERVAL_S):
            self.peak_rss = max(self.peak_rss, self._process.memory_info().rss)
            self.peak_threads = max(self.peak_threads, self._process.num_threads())

    def rss(self) -> int:
        return self._process.memory_info().rss

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        self.peak_rss = max(self.peak_rss, self.rss())


def _cgroup_mb(name: str) -> float | None:
    """A cgroup v2 memory value of this container, or None outside one."""
    try:
        raw = Path(f"/sys/fs/cgroup/{name}").read_text().strip()
    except OSError:
        return None
    return None if raw == "max" else round(int(raw) / 1e6, 1)


def _mb(value: int) -> float:
    return round(value / 1e6, 1)


def run(
    attempt_id: int,
    cc_pair_id: int,
    batches: int,
    threads: int,
    cprofile_out: str | None = None,
) -> RunResult:
    """Runs the body of `docprocessing_task` for each batch on a thread pool, as
    the Celery worker does (worker_pool = threads)."""
    if cprofile_out is not None:
        # The interpreter allows one active profiler, so a profiled run has
        # one worker thread.
        threads = 1
    _init(pool_size=threads)
    # Fail fast on a wrong Redis instead of inside the first batch.
    get_redis_client(tenant_id=_TENANT_ID).ping()

    pending: queue.Queue[int] = queue.Queue()
    for batch_num in range(batches):
        pending.put(batch_num)

    batch_seconds: list[float] = []
    batch_errors: list[str] = []
    lock = threading.Lock()

    profile = cProfile.Profile() if cprofile_out is not None else None

    def work() -> None:
        if profile is None:
            drain()
            return
        profile.enable()
        try:
            drain()
        finally:
            profile.disable()

    def drain() -> None:
        while True:
            try:
                batch_num = pending.get_nowait()
            except queue.Empty:
                return
            started = time.monotonic()
            try:
                _docprocessing_task(
                    attempt_id,
                    cc_pair_id,
                    _TENANT_ID,
                    batch_num,
                    enqueue_time_ms=None,
                )
            except Exception as e:
                with lock:
                    batch_errors.append(f"batch {batch_num}: {type(e).__name__}: {e}")
            else:
                with lock:
                    batch_seconds.append(time.monotonic() - started)

    sampler = _MemorySampler()
    rss_start = sampler.rss()
    heartbeat_thread, heartbeat_stop = start_heartbeat(attempt_id)
    sampler.start()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()

    workers = [
        threading.Thread(target=work, name=f"docprocessing-{i}") for i in range(threads)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    elapsed = time.monotonic() - started
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    sampler.stop()
    heartbeat_stop.set()
    heartbeat_thread.join()

    if profile is not None and cprofile_out is not None:
        # In this thread, so a write error fails the phase.
        profile.dump_stats(cprofile_out)

    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(db_session, attempt_id)
        if attempt is None:
            raise RuntimeError(f"Index attempt {attempt_id} not found")
        errors = get_index_attempt_errors(attempt_id, db_session)
        metrics = [
            StageMetric(
                stage=row.stage.value,
                events=row.event_count,
                total_ms=row.total_duration_ms,
                mean_ms=round(row.total_duration_ms / max(row.event_count, 1), 2),
                max_ms=row.max_duration_ms,
            )
            for row in get_stage_metrics_for_attempt(db_session, attempt_id)
        ]
        ordered = sorted(batch_seconds)
        return RunResult(
            threads=threads,
            batches=batches,
            failed_batches=len(batch_errors),
            batch_errors=batch_errors[:10],
            elapsed_seconds=round(elapsed, 3),
            cpu_user_seconds=round(usage_after.ru_utime - usage_before.ru_utime, 3),
            cpu_system_seconds=round(usage_after.ru_stime - usage_before.ru_stime, 3),
            rss_start_mb=_mb(rss_start),
            rss_peak_mb=_mb(sampler.peak_rss),
            rss_end_mb=_mb(sampler.rss()),
            cgroup_memory_peak_mb=_cgroup_mb("memory.peak"),
            cgroup_memory_limit_mb=_cgroup_mb("memory.max"),
            threads_peak=sampler.peak_threads,
            attempt_status=attempt.status.value,
            completed_batches=attempt.completed_batches,
            total_batches=attempt.total_batches,
            total_docs_indexed=attempt.total_docs_indexed or 0,
            new_docs_indexed=attempt.new_docs_indexed or 0,
            total_chunks=attempt.total_chunks,
            error_rows=len(errors),
            error_document_ids=sorted(
                error.document_id for error in errors if error.document_id
            )[:50],
            heartbeat_counter=attempt.heartbeat_counter,
            stage_metrics=metrics,
            batch_seconds_p50=round(ordered[len(ordered) // 2], 3) if ordered else 0.0,
            batch_seconds_max=round(ordered[-1], 3) if ordered else 0.0,
        )


def _canonical(value: Any) -> Any:
    """Rounds vectors, so a float that differs in its last bit does not change
    the digest."""
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def verify(spec: CorpusSpec, index_name: str, cc_pair_id: int) -> VerifyResult:
    _init(pool_size=2)
    _require_bench_name("index", index_name)

    client = _opensearch()
    client.indices.refresh(index=index_name)
    chunk_hashes: list[bytes] = []
    chunk_indexes: dict[str, list[int]] = {}
    for hit in scan(
        client,
        index=index_name,
        query={"query": {"match_all": {}}, "_source": list(_DIGEST_FIELDS)},
        size=500,
        scroll="5m",
    ):
        source: dict[str, Any] = hit["_source"]
        chunk_indexes.setdefault(source[DOCUMENT_ID_FIELD_NAME], []).append(
            source[CHUNK_INDEX_FIELD_NAME]
        )
        canonical = {name: _canonical(source.get(name)) for name in _DIGEST_FIELDS}
        chunk_hashes.append(
            hashlib.sha256(
                json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
            ).digest()
        )
    client.close()

    index_digest = hashlib.sha256()
    for chunk_hash in sorted(chunk_hashes):
        index_digest.update(chunk_hash)

    duplicate_chunks = 0
    documents_with_gaps: list[str] = []
    for doc_id, indexes in chunk_indexes.items():
        duplicate_chunks += len(indexes) - len(set(indexes))
        if sorted(set(indexes)) != list(range(len(set(indexes)))):
            documents_with_gaps.append(doc_id)

    expected = {doc.doc_id for doc in iter_doc_specs(spec) if not doc.poisoned}
    indexed = set(chunk_indexes)

    with get_session_with_current_tenant() as db_session:
        rows = db_session.execute(
            select(
                DBDocument.id,
                DBDocument.chunk_count,
                DBDocument.semantic_id,
                DBDocument.content_hash,
                DBDocument.doc_updated_at,
            ).order_by(DBDocument.id)
        ).all()
        cc_pair_links = len(
            db_session.execute(
                select(DocumentByConnectorCredentialPair.id)
                .join(
                    ConnectorCredentialPair,
                    (
                        ConnectorCredentialPair.connector_id
                        == DocumentByConnectorCredentialPair.connector_id
                    )
                    & (
                        ConnectorCredentialPair.credential_id
                        == DocumentByConnectorCredentialPair.credential_id
                    ),
                )
                .where(ConnectorCredentialPair.id == cc_pair_id)
            ).all()
        )

    postgres_digest = hashlib.sha256()
    chunk_count_mismatches: list[str] = []
    documents_without_content_hash = 0
    for row in rows:
        postgres_digest.update(
            json.dumps(
                [
                    row.id,
                    row.chunk_count,
                    row.semantic_id,
                    row.content_hash,
                    row.doc_updated_at.astimezone(UTC).isoformat()
                    if row.doc_updated_at
                    else None,
                ]
            ).encode()
        )
        in_index = len(set(chunk_indexes.get(row.id, [])))
        # A document that never reached the index keeps a NULL count.
        if (row.chunk_count or 0) != in_index:
            chunk_count_mismatches.append(row.id)
        if row.id in indexed and row.content_hash is None:
            documents_without_content_hash += 1

    return VerifyResult(
        index_chunks=len(chunk_hashes),
        index_documents=len(indexed),
        index_digest=index_digest.hexdigest(),
        duplicate_chunks=duplicate_chunks,
        documents_with_gaps=sorted(documents_with_gaps)[:20],
        missing_documents=sorted(expected - indexed)[:20],
        unexpected_documents=sorted(indexed - expected)[:20],
        chunk_count_mismatches=sorted(chunk_count_mismatches)[:20],
        postgres_documents=len(rows),
        postgres_digest=postgres_digest.hexdigest(),
        documents_without_content_hash=documents_without_content_hash,
        cc_pair_links=cc_pair_links,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["setup", "stage", "run", "verify"])
    parser.add_argument("--index-name", default=f"{BENCH_PREFIX}_index")
    parser.add_argument("--corpus", default="{}", help="CorpusSpec as JSON")
    parser.add_argument("--revision", type=int, default=0)
    parser.add_argument("--cc-pair-id", type=int, default=0)
    parser.add_argument("--attempt-id", type=int, default=0)
    parser.add_argument("--batches", type=int, default=0)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument(
        "--cprofile-out", help="write a cProfile here; the run then uses one thread"
    )
    args = parser.parse_args()

    spec = CorpusSpec.model_validate_json(args.corpus)
    if args.phase == "setup":
        _emit(setup(args.index_name))
    elif args.phase == "stage":
        _emit(stage(spec, args.revision, args.cc_pair_id))
    elif args.phase == "run":
        _emit(
            run(
                args.attempt_id,
                args.cc_pair_id,
                args.batches,
                args.threads,
                args.cprofile_out,
            )
        )
    else:
        _emit(verify(spec, args.index_name, args.cc_pair_id))


if __name__ == "__main__":
    main()
