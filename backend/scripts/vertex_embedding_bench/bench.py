"""Benchmark Onyx docprocessing embedding throughput and memory against a
mock Vertex server.

One trial = one fresh subprocess that acts like one docprocessing pod:
`--pod-concurrency` threads (celery `--concurrency`) in one process, each
repeatedly taking a batch of documents and running Onyx's real embed path
(`embed_and_stream` -> `embed_chunks_with_failure_handling` ->
`DefaultIndexingEmbedder.embed_chunks` -> `EmbeddingModel.encode` ->
`_batch_encode_texts` thread pool -> `CloudEmbedding._embed_vertex` ->
google-genai) with Google / gemini-embedding-2 and service-account auth.

Example:
    PYTHONPATH=<onyx backend> python bench.py --profile unlimited_300ms \
        --pod-concurrency 4 --duration 120 --label baseline
    PYTHONPATH=<onyx backend> python bench.py --profile unlimited_300ms \
        --env EMBEDDING_BATCH_SIZE=8 --env INDEXING_EMBEDDING_MODEL_NUM_THREADS=32 \
        --label bs8_t32

Each trial appends one JSON line to results.jsonl. See summarize.py.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import pickle
import random
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent
CACHE = HERE / ".cache"
DEFAULT_CHUNKS = CACHE / "chunks-synthetic"
DEFAULT_RESULTS = HERE / "results.jsonl"
MODEL_NAME = "gemini-embedding-2"

# Env defaults for the Onyx process: a Cloud docprocessing pod.
DEFAULT_ONYX_ENV = {
    "MULTI_TENANT": "true",
    "LOG_LEVEL": "info",
    "SKIP_WARM_UP": "true",
}


# --------------------------------------------------------------------------
# Parent: orchestration, RSS sampling, results
# --------------------------------------------------------------------------


def _http(method: str, url: str, timeout: float = 5.0) -> dict[str, Any]:
    r = httpx.request(method, url, timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else {}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=BACKEND, capture_output=True, text=True, check=False
    ).stdout


def git_info() -> dict[str, str]:
    # A container has no git: docker_trial.sh passes the host's values.
    if os.environ.get("BENCH_GIT_INFO"):
        return json.loads(os.environ["BENCH_GIT_INFO"])
    diff = _git("diff", "HEAD", "--", ".", ":(exclude)scripts/vertex_embedding_bench")
    return {
        "head": _git("rev-parse", "HEAD").strip(),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest()[:16] if diff else "clean",
        "diff_lines": str(diff.count("\n")),
    }


def merged_profiles_file() -> Path:
    base = HERE / "profiles.json"
    if not base.exists():
        base = HERE / "profiles.default.json"
    data = json.loads(base.read_text())
    data.update(json.loads((HERE / "bench_profiles.json").read_text()))
    out = CACHE / "merged_profiles.json"
    CACHE.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    return out


def ensure_sa(port: int, host: str = "127.0.0.1") -> Path:
    sa = CACHE / f"fake_service_account_{host}_{port}.json"
    if not sa.exists():
        subprocess.run(
            [
                sys.executable,
                str(HERE / "mock_vertex.py"),
                "--write-sa",
                str(sa),
                "--port",
                str(port),
                "--sa-host",
                host,
            ],
            check=True,
            capture_output=True,
        )
    return sa


def start_mock(
    port: int, profile: str, latency_scale: float
) -> subprocess.Popen[bytes]:
    log = open(CACHE / f"mock_{port}.log", "ab")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "mock_vertex.py"),
            "--port",
            str(port),
            "--profiles",
            str(merged_profiles_file()),
            "--profile",
            profile,
            "--latency-scale",
            str(latency_scale),
        ],
        stdout=log,
        stderr=log,
        cwd=HERE,
    )
    for _ in range(100):
        try:
            _http("GET", f"http://127.0.0.1:{port}/healthz", timeout=1)
            return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit(f"mock exited; see {CACHE / f'mock_{port}.log'}")
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("mock did not start")


def _stop_mock(proc: subprocess.Popen[bytes]) -> None:
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _free_port(start: int) -> int:
    import socket

    for port in range(start, start + 50):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free port for the mock")


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


STAT_KEYS = (
    "requests",
    "ok",
    "throttled_429",
    "errors_5xx",
    "bad_request_400",
    "unauthenticated_401",
    "inputs",
    "input_tokens",
    "token_requests",
)


def _status(oom: bool, timed_out: bool, rc: int, result: dict[str, Any]) -> str:
    if oom:
        return "oom"
    if timed_out:
        return "timeout"
    if rc != 0 or not result:
        return f"crash(rc={rc})"
    if result["worker_setup_errors"]:
        return "worker_error"
    return "ok"


def run_parent(args: argparse.Namespace) -> None:
    import psutil

    CACHE.mkdir(exist_ok=True)
    if not (args.chunks_dir / "index.json").exists():
        print(
            "chunk cache missing; building it with prepare_chunks.py", file=sys.stderr
        )
        subprocess.run(
            [
                sys.executable,
                str(HERE / "prepare_chunks.py"),
                "--out",
                str(args.chunks_dir),
            ],
            check=True,
        )
    index_fp = json.loads((args.chunks_dir / "index.json").read_text())["fingerprint"]

    mock_proc = None
    if args.mock_url:
        mock_url = args.mock_url.rstrip("/")
        port = int(mock_url.rsplit(":", 1)[1])
    else:
        # Use the mock on --mock-port when it runs and has the profile. Else
        # start a private mock (bench_profiles.json merged in) on a free port.
        port = args.mock_port
        mock_url = f"http://127.0.0.1:{port}"
        try:
            have = _http("GET", f"{mock_url}/profiles", timeout=1).get("profiles", {})
        except (httpx.HTTPError, ValueError):
            have = None
        if have is None:
            mock_proc = start_mock(port, args.profile, args.latency_scale)
        elif args.profile not in have:
            port = _free_port(args.spawn_port)
            mock_url = f"http://127.0.0.1:{port}"
            print(
                f"mock on {args.mock_port} has no profile {args.profile!r}; "
                f"starting a private mock on {port}",
                file=sys.stderr,
            )
            mock_proc = start_mock(port, args.profile, args.latency_scale)
    child: subprocess.Popen[bytes] | None = None
    try:
        _http(
            "POST",
            f"{mock_url}/profile/{args.profile}?latency_scale={args.latency_scale}",
        )
        sa_path = ensure_sa(port, args.sa_host)

        onyx_env = dict(DEFAULT_ONYX_ENV)
        for kv in args.env:
            k, _, v = kv.partition("=")
            onyx_env[k] = v
        env = dict(os.environ)
        env.update(onyx_env)
        env["PYTHONPATH"] = str(BACKEND) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["GOOGLE_VERTEX_BASE_URL"] = f"{mock_url}/"
        env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        label = args.label or f"trial-{int(time.time())}"
        run_dir = CACHE / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
        run_dir.mkdir(parents=True)
        child_cfg = {
            "chunks_dir": str(args.chunks_dir.resolve()),
            "sa_path": str(sa_path),
            "pod_concurrency": args.pod_concurrency,
            "duration": args.duration,
            "warmup": args.warmup,
            "docs_per_batch": args.docs_per_batch,
            "min_chunks_per_doc": args.min_chunks_per_doc,
            "max_chunks_per_doc": args.max_chunks_per_doc,
            "seed": args.seed,
            "reduced_dimension": args.reduced_dimension,
            "tenant_id": args.tenant_id,
            "vertex_location": args.vertex_location,
            "ready_file": str(run_dir / "ready"),
            "go_file": str(run_dir / "go"),
            "result_file": str(run_dir / "result.json"),
        }
        (run_dir / "config.json").write_text(json.dumps(child_cfg, indent=1))

        _http("POST", f"{mock_url}/reset")
        log = open(run_dir / "onyx.log", "wb")
        t_spawn = time.time()
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                str(run_dir / "config.json"),
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=run_dir,
        )
        proc = psutil.Process(child.pid)
        limit = args.mem_limit_gb * 1024**3 if args.mem_limit_gb else None
        samples: list[tuple[float, int, int]] = []  # (t, rss, os_threads)
        t_ready: float | None = None
        cpu_at_ready = None
        cpu_last = None
        oom = False
        timed_out = False
        hard_deadline = t_spawn + args.duration + args.setup_timeout
        while child.poll() is None:
            try:
                rss = proc.memory_info().rss
                nthreads = proc.num_threads()
                cpu_last = proc.cpu_times()
            except psutil.Error:
                break
            now = time.time()
            samples.append((now, rss, nthreads))
            if t_ready is None and os.path.exists(child_cfg["ready_file"]):
                # Setup traffic is done and the workers wait for the go file,
                # so the mock counters from here on are the trial's alone.
                _http("POST", f"{mock_url}/reset")
                cpu_at_ready = proc.cpu_times()
                t_ready = time.time()
                Path(child_cfg["go_file"]).touch()
            if limit and rss > limit:
                oom = True
                child.kill()
                break
            if now > hard_deadline:
                timed_out = True
                child.kill()
                break
            time.sleep(0.1)
        cpu_end = cpu_last
        t_end = samples[-1][0] if samples else time.time()
        child.wait()
        stats_end = _http("GET", f"{mock_url}/stats")
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        if mock_proc is not None and not args.keep_mock:
            _stop_mock(mock_proc)

    result: dict[str, Any] = {}
    if os.path.exists(child_cfg["result_file"]):
        result = json.loads(Path(child_cfg["result_file"]).read_text())

    window = [r for t, r, _ in samples if t_ready and t >= t_ready]
    baseline_rss = result.get("baseline_rss") or (window[0] if window else 0)
    peak_rss = max((r for _, r, _ in samples), default=0)
    window_peak_rss = max(window, default=baseline_rss)
    mock_stats = {
        k: stats_end.get(k) for k in (*STAT_KEYS, "peak_in_flight", "throttle_reasons")
    }
    cpu_util = None
    if cpu_at_ready is not None and cpu_end is not None and t_ready:
        used = (cpu_end.user + cpu_end.system) - (
            cpu_at_ready.user + cpu_at_ready.system
        )
        cpu_util = round(used / max(1e-6, t_end - t_ready), 3)

    status = _status(oom, timed_out, child.returncode, result)
    gb = 1024**3
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": label,
        "status": status,
        "git": git_info(),
        "chunk_set": index_fp,
        "config": {
            "profile": args.profile,
            "latency_scale": args.latency_scale,
            "pod_concurrency": args.pod_concurrency,
            "duration": args.duration,
            "warmup": args.warmup,
            "docs_per_batch": args.docs_per_batch,
            "min_chunks_per_doc": args.min_chunks_per_doc,
            "max_chunks_per_doc": args.max_chunks_per_doc,
            "seed": args.seed,
            "reduced_dimension": args.reduced_dimension,
            "mem_limit_gb": args.mem_limit_gb,
            "mock_url": mock_url,
            "vertex_location": args.vertex_location,
            "env": onyx_env,
        },
        "metrics": {
            **{k: v for k, v in result.items() if k != "baseline_rss"},
            "baseline_rss_gb": round(baseline_rss / gb, 3),
            "peak_rss_gb": round(peak_rss / gb, 3),
            "p95_rss_gb": round(_pct([float(x) for x in window], 0.95) / gb, 3),
            "peak_rss_delta_gb": round((window_peak_rss - baseline_rss) / gb, 3),
            "max_os_threads": max((n for _, _, n in samples), default=0),
            "cpu_cores_used": cpu_util,
            "rss_samples": len(samples),
        },
        "mock": mock_stats,
        "run_dir": str(run_dir),
    }
    with open(args.results, "a") as f:
        f.write(json.dumps(record) + "\n")
    m = record["metrics"]
    print(
        json.dumps(
            {
                "label": label,
                "status": status,
                "inputs_per_min": m.get("steady_inputs_per_min"),
                "pipeline_chunks": m.get("pipeline_chunks_ok"),
                "failed_chunks": m.get("failed_chunks"),
                "peak_rss_gb": m["peak_rss_gb"],
                "peak_rss_delta_gb": m["peak_rss_delta_gb"],
                "mock_429": mock_stats["throttled_429"],
                "mock_peak_in_flight": mock_stats["peak_in_flight"],
                "client_avg_in_flight": m.get("client_avg_in_flight"),
            }
        )
    )


# --------------------------------------------------------------------------
# Child: one docprocessing "pod"
# --------------------------------------------------------------------------


class _Calls:
    """Client-side view of each google-genai embed_content call."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ids = itertools.count()
        self.active: dict[int, float] = {}  # call id -> start
        self.peak_in_flight = 0
        self.done: list[tuple[float, float, int]] = []  # (start, end, n_inputs)
        self.failed: list[tuple[float, float]] = []  # (start, end)
        self.errors: dict[str, int] = {}

    def wrap(self, fn: Any) -> Any:
        calls = self

        async def embed_content(self_: Any, *a: Any, **kw: Any) -> Any:
            contents = kw.get("contents")
            n = len(contents) if isinstance(contents, list) else 1
            t0 = time.monotonic()
            with calls.lock:
                call_id = next(calls.ids)
                calls.active[call_id] = t0
                calls.peak_in_flight = max(calls.peak_in_flight, len(calls.active))
            try:
                resp = await fn(self_, *a, **kw)
            except BaseException as e:
                key = f"{type(e).__name__}:{vars(e).get('code', '')}"
                with calls.lock:
                    del calls.active[call_id]
                    calls.failed.append((t0, time.monotonic()))
                    calls.errors[key] = calls.errors.get(key, 0) + 1
                raise
            with calls.lock:
                del calls.active[call_id]
                calls.done.append((t0, time.monotonic(), n))
            return resp

        return embed_content


def _call_metrics(
    calls: _Calls, w0: float, t_end: float, duration: float
) -> dict[str, Any]:
    """Throughput and latency of the successful calls that ended in
    [w0, t_end]. Mean concurrency also counts failed and unfinished calls."""
    with calls.lock:
        done = list(calls.done)
        spans = [(s, e) for s, e, _ in done] + calls.failed
        spans += [(s, t_end) for s in calls.active.values()]
        errors = dict(calls.errors)
        client_peak = calls.peak_in_flight
    steady_inputs = sum(n for s, e, n in done if w0 <= e <= t_end)
    total_inputs = sum(n for s, e, n in done if e <= t_end)
    steady_secs = max(1e-6, t_end - w0)
    busy = sum(max(0.0, min(e, t_end) - max(s, w0)) for s, e in spans)
    lat = [e - s for s, e, _ in done if w0 <= e <= t_end]
    # A provider input is not always a useful chunk: the pipeline can retry a
    # failed batch per document, and it drops the chunks of failed documents.
    return {
        "steady_window_s": round(steady_secs, 1),
        "steady_inputs": steady_inputs,
        "steady_inputs_per_min": round(steady_inputs / steady_secs * 60, 1),
        "total_inputs_embedded": total_inputs,
        "overall_inputs_per_min": round(total_inputs / duration * 60, 1),
        "client_calls": len(done),
        "client_avg_in_flight": round(busy / steady_secs, 2),
        "client_peak_in_flight": client_peak,
        "call_latency_p50_s": round(_pct(lat, 0.5), 3),
        "call_latency_p95_s": round(_pct(lat, 0.95), 3),
        "client_call_errors": errors,
    }


class _DocQueue:
    """Shared doc queue: like celery handing doc batches to free threads."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.chunks_dir = Path(cfg["chunks_dir"])
        index = json.loads((self.chunks_dir / "index.json").read_text())
        min_cpd = max(1, cfg["min_chunks_per_doc"])
        self.docs = [d for d in index["docs"] if d["n_chunks"] >= min_cpd]
        random.Random(cfg["seed"]).shuffle(self.docs)
        self.max_cpd = cfg["max_chunks_per_doc"]
        self.docs_per_batch = cfg["docs_per_batch"]
        self.lock = threading.Lock()
        self.pos = 0

    def load(self, entry: dict[str, Any]) -> list[Any]:
        with open(self.chunks_dir / entry["file"], "rb") as f:
            chunks = pickle.load(f)  # noqa: S301 - prepare_chunks.py wrote it
        return chunks[: self.max_cpd] if self.max_cpd else chunks

    def next_batch(self) -> list[Any]:
        with self.lock:
            start, self.pos = self.pos, self.pos + self.docs_per_batch
        chunks: list[Any] = []
        for i in range(start, start + self.docs_per_batch):
            chunks.extend(self.load(self.docs[i % len(self.docs)]))
        return chunks


def _add_wait_totals(into: dict[str, Any], embedders: Iterable[Any]) -> None:
    for embedder in embedders:
        rl, pt = embedder.embedding_model.wait_totals.snapshot()
        into["rate_limit_wait_s"] += rl
        into["provider_throttle_wait_s"] += pt


def _wait_for_file(path: str) -> None:
    while not os.path.exists(path):
        time.sleep(0.05)


def run_child(cfg_path: str) -> None:
    import resource
    from unittest import mock

    import psutil

    cfg = json.loads(Path(cfg_path).read_text())

    from google.genai import models as genai_models

    import onyx.natural_language_processing.search_nlp_models as nlp
    from onyx.connectors.models import ConnectorStopSignal
    from onyx.indexing.embedder import DefaultIndexingEmbedder
    from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
    from onyx.indexing.indexing_pipeline import embed_and_stream
    from onyx.natural_language_processing.embedding_auth import build_embedding_auth
    from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
    from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
    from shared_configs.configs import (
        INDEXING_MODEL_SERVER_HOST,
        INDEXING_MODEL_SERVER_PORT,
    )
    from shared_configs.enums import EmbeddingProvider

    # Stub: no admin-configured embedding rate limit (load_settings needs
    # Postgres + Redis). This is the "no limit configured" branch.
    mock.patch.object(nlp, "load_embedding_rate_limiter", return_value=None).start()

    calls = _Calls()
    genai_models.AsyncModels.embed_content = calls.wrap(  # type: ignore[method-assign]
        genai_models.AsyncModels.embed_content
    )

    stop = threading.Event()

    class Callback(IndexingHeartbeatInterface):
        def should_stop(self) -> bool:
            return stop.is_set()

        def progress(self, tag: str, amount: int) -> None:
            pass

    sa_json = Path(cfg["sa_path"]).read_text()

    vertex_config = VertexEmbeddingConfig(
        auth_method="service_account_json", location=cfg["vertex_location"]
    )

    def make_embedder() -> DefaultIndexingEmbedder:
        # The task builds a new embedder per doc batch, the way
        # DefaultIndexingEmbedder.from_db_search_settings does: the
        # EmbeddingModel gets auth from the stored SA JSON + vertex_config.
        callback = Callback()
        model = EmbeddingModel(
            server_host=INDEXING_MODEL_SERVER_HOST,
            server_port=INDEXING_MODEL_SERVER_PORT,
            model_name=MODEL_NAME,
            normalize=True,
            query_prefix=None,
            passage_prefix=None,
            api_key=sa_json,
            api_url=None,
            provider_type=EmbeddingProvider.GOOGLE,
            retrim_content=True,
            callback=callback,
            reduced_dimension=cfg["reduced_dimension"],
            auth=build_embedding_auth(EmbeddingProvider.GOOGLE, sa_json, vertex_config),
        )
        return DefaultIndexingEmbedder(
            model_name=MODEL_NAME,
            normalize=True,
            query_prefix=None,
            passage_prefix=None,
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=sa_json,
            reduced_dimension=cfg["reduced_dimension"],
            callback=callback,
            embedding_model=model,
        )

    queue = _DocQueue(cfg)

    # Warmup: imports, tokenizer, auth, one real call; also checks the dim.
    warm = queue.load(queue.docs[0])[:2]
    vecs = make_embedder().embed_chunks(warm, tenant_id=cfg["tenant_id"])
    dim = len(vecs[0].embeddings.full_embedding)
    del warm, vecs
    with calls.lock:
        calls.done.clear()
        calls.failed.clear()
        calls.peak_in_flight = 0

    Path(cfg["ready_file"]).touch()
    # The parent takes the mock baseline before it writes the go file.
    _wait_for_file(cfg["go_file"])
    baseline_rss = psutil.Process().memory_info().rss
    t_start = time.monotonic()

    lock = threading.Lock()
    tot = {
        "batches_done": 0,
        "pipeline_chunks_ok": 0,
        "failed_chunks": 0,
        "failed_docs": 0,
        "batch_exceptions": 0,
        "worker_setup_errors": 0,
        "rate_limit_wait_s": 0.0,
        "provider_throttle_wait_s": 0.0,
        "chunks_started": 0,
    }
    active_embedders: dict[int, DefaultIndexingEmbedder] = {}
    exc_samples: list[str] = []
    failure_samples: list[str] = []
    batch_secs: list[float] = []

    def worker(i: int) -> None:
        n = 0
        while not stop.is_set():
            try:
                chunks = queue.next_batch()
                embedder = make_embedder()
            except Exception as e:  # noqa: BLE001
                with lock:
                    tot["worker_setup_errors"] += 1
                    if len(exc_samples) < 10:
                        exc_samples.append(repr(e)[:300])
                return
            with lock:
                tot["chunks_started"] += len(chunks)
                active_embedders[i] = embedder
            t0 = time.monotonic()
            try:
                with embed_and_stream(
                    chunks, embedder, cfg["tenant_id"], f"bench-{i}-{n}"
                ) as (result, store):
                    # Stub of the vector-DB write: stream the spilled
                    # embedded chunks back, as the real write does.
                    for _ in store.stream():
                        pass
                failed_ids = {
                    f.failed_document.document_id
                    for f in result.connector_failures
                    if f.failed_document
                }
                n_failed = sum(1 for c in chunks if c.source_document.id in failed_ids)
                with lock:
                    tot["batches_done"] += 1
                    tot["pipeline_chunks_ok"] += len(result.successful_chunk_ids)
                    tot["failed_chunks"] += n_failed
                    tot["failed_docs"] += len(failed_ids)
                    batch_secs.append(time.monotonic() - t0)
                    for f in result.connector_failures[:2]:
                        if len(failure_samples) < 10:
                            failure_samples.append(f.failure_message[:300])
            except ConnectorStopSignal:
                break
            except Exception as e:  # noqa: BLE001
                if stop.is_set():
                    break
                with lock:
                    tot["batch_exceptions"] += 1
                    tot["failed_chunks"] += len(chunks)
                    if len(exc_samples) < 10:
                        exc_samples.append(repr(e)[:300])
            finally:
                with lock:
                    del active_embedders[i]
                    _add_wait_totals(tot, [embedder])
            del chunks, embedder
            n += 1

    py_threads_peak = [threading.active_count()]

    def sampler() -> None:
        while not stop.is_set():
            py_threads_peak[0] = max(py_threads_peak[0], threading.active_count())
            time.sleep(0.1)

    threading.Thread(target=sampler, daemon=True).start()
    for i in range(cfg["pod_concurrency"]):
        threading.Thread(
            target=worker, args=(i,), daemon=True, name=f"celery-{i}"
        ).start()

    t_end = t_start + cfg["duration"]
    while time.monotonic() < t_end:
        time.sleep(0.2)
    stop.set()

    with lock:
        totals = dict(tot)
        _add_wait_totals(totals, active_embedders.values())
    result = {
        "baseline_rss": baseline_rss,
        "embedding_dim": dim,
        "pod_concurrency": cfg["pod_concurrency"],
        **_call_metrics(calls, t_start + cfg["warmup"], t_end, cfg["duration"]),
        **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in totals.items()},
        "batch_seconds_p50": round(_pct(batch_secs, 0.5), 1),
        "exception_samples": exc_samples,
        "failure_samples": failure_samples,
        "max_py_threads": py_threads_peak[0],
        "ru_maxrss_gb": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**3 if sys.platform == "darwin" else 1024**2),
            3,
        ),
        "effective": {
            "BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES": nlp.BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES,
            "INDEXING_EMBEDDING_MODEL_NUM_THREADS": nlp.INDEXING_EMBEDDING_MODEL_NUM_THREADS,
            "MULTI_TENANT": os.environ.get("MULTI_TENANT"),
        },
    }
    Path(cfg["result_file"]).write_text(json.dumps(result, indent=1))
    sys.stdout.flush()
    # In-flight encode calls do not check the stop signal; do not wait for them.
    os._exit(0)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        run_child(sys.argv[2])
        return
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--profile", default="unlimited_300ms", help="mock profile name")
    ap.add_argument("--latency-scale", type=float, default=1.0)
    ap.add_argument("--pod-concurrency", type=int, default=4, help="celery threads")
    ap.add_argument(
        "--duration", type=float, default=120, help="seconds after warmup call"
    )
    ap.add_argument(
        "--warmup", type=float, default=20, help="seconds excluded from steady rate"
    )
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL")
    ap.add_argument("--label", default="")
    ap.add_argument(
        "--docs-per-batch", type=int, default=16, help="INDEX_BATCH_SIZE default"
    )
    ap.add_argument(
        "--min-chunks-per-doc", type=int, default=0, help="skip smaller docs"
    )
    ap.add_argument(
        "--max-chunks-per-doc", type=int, default=0, help="truncate docs (0=off)"
    )
    ap.add_argument("--seed", type=int, default=1, help="doc order")
    ap.add_argument("--reduced-dimension", type=int, default=None)
    ap.add_argument("--tenant-id", default="tenant_bench")
    ap.add_argument("--mem-limit-gb", type=float, default=12.0, help="0 = no limit")
    ap.add_argument(
        "--mock-url", default="", help="use this running mock instead of starting one"
    )
    ap.add_argument(
        "--sa-host",
        default="127.0.0.1",
        help="host in the fake service account token_uri (host.docker.internal in a container)",
    )
    ap.add_argument(
        "--mock-port",
        type=int,
        default=8799,
        help="mock to use; started here if nothing listens on it",
    )
    ap.add_argument(
        "--spawn-port",
        type=int,
        default=8791,
        help="first port tried for a private mock when --mock-port lacks the profile",
    )
    ap.add_argument("--vertex-location", default="us-central1")
    ap.add_argument("--keep-mock", action="store_true")
    ap.add_argument("--setup-timeout", type=float, default=300)
    ap.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS)
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    run_parent(ap.parse_args())


if __name__ == "__main__":
    main()
