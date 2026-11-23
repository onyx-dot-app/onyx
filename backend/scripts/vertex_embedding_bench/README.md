# Vertex embedding throughput benchmark

This directory measures the indexing embedding throughput and memory of one
docprocessing pod. The embedding provider is Google Vertex AI with
gemini-embedding-2. A local mock replaces Vertex AI, so you need no Google
account and you pay nothing.

## What it measures

`bench.py` runs one trial in a new subprocess. The subprocess acts like one
docprocessing pod. It starts `--pod-concurrency` threads (celery
`--concurrency`). Each thread takes a batch of documents and runs the real Onyx
embed path:

`embed_and_stream` -> `DefaultIndexingEmbedder.embed_chunks` ->
`EmbeddingModel.encode` -> `CloudEmbedding._embed_vertex` -> google-genai.

The parent process samples the RSS and the thread count of the subprocess. It
reads the request counters from the mock. At the end, it adds one JSON line to
`results.jsonl`.

## Files

| File | Use |
|---|---|
| `bench.py` | Runs one trial. |
| `mock_vertex.py` | Mock Vertex AI embedding API and OAuth token endpoint. |
| `prepare_chunks.py` | Builds the chunk set (the workload). |
| `summarize.py` | Prints a table of trials. |
| `smoke_sdk.py` | Checks the mock with the google-genai SDK and with Onyx. |
| `load_mock.py` | Measures the raw capacity of the mock. |
| `docker_trial.sh` | Runs one trial in a container with CPU and memory limits. |
| `sweep_quota.sh` | Runs each quota profile at several concurrency limits. Needs onyx PR #18315. |
| `Dockerfile.bench` | Image for container trials. |
| `profiles.json` | Quota and latency profiles from research. See [VERTEX_LIMITS.md](VERTEX_LIMITS.md). |
| `profiles.default.json` | Placeholder profiles. The mock uses them when `profiles.json` is absent. |
| `bench_profiles.json` | Extra profiles for `bench.py`, for example `unlimited_300ms`. |

## Quick start

Use a Python environment with the Onyx backend requirements. Run all commands
from this directory.

```bash
export PYTHONPATH=$(cd ../.. && pwd)   # the Onyx backend directory

# 1. Build the chunk set. bench.py also does this when the set is missing.
python prepare_chunks.py

# 2. Run one trial. If no mock listens on --mock-port (8799), bench.py starts
#    one and writes a fake service account to .cache/.
python bench.py --profile unlimited_300ms --pod-concurrency 4 --duration 120 --label baseline

# 3. Change one setting and compare.
python bench.py --env INDEXING_EMBEDDING_MODEL_NUM_THREADS=32 --label t32
python summarize.py --last 2
```

`--env KEY=VAL` sets an environment variable in the Onyx process. The defaults
are `MULTI_TENANT=true`, `LOG_LEVEL=info` and `SKIP_WARM_UP=true`.

To run the mock yourself:

```bash
python mock_vertex.py --write-sa .cache/mock-sa.json --port 8799   # fake service account
python mock_vertex.py --port 8799 --profile vertex_paygo_dsq       # serve
python smoke_sdk.py --base-url http://127.0.0.1:8799/ --sa .cache/mock-sa.json --onyx
```

Use the same `--port` for `--write-sa` and for the server. The `token_uri` of
the service account points to the mock. Set
`GOOGLE_VERTEX_BASE_URL=http://127.0.0.1:8799/` and google-genai sends its
requests to the mock. Onyx needs no code change.

## Workload

By default, `prepare_chunks.py` generates 300 synthetic documents from a fixed
seed. The text has headings, prose and Markdown tables with financial numbers.
Onyx's real `Chunker` splits the documents. The number of chunks per document
follows a distribution from a public corpus of 1,435 financial reports: median
66, p90 about 1,800, maximum 4,264, and about 120,000 chunks in total. The
median chunk has about 1,170 characters.

`--corpus-dir DIR` chunks a directory of parsed-document JSON files instead.
`--docs` and `--seed` select the documents. `index.json` holds a fingerprint of
the chunk set, and each result records it as `chunk_set`. Compare only trials
with the same `chunk_set`.

## Container trials

A trial on a laptop has no pod limits. To apply CPU and memory limits like a
Kubernetes pod, run the trial in a container.

```bash
# Build the image from the backend directory. BASE_IMAGE is optional.
(cd ../.. && docker build -f scripts/vertex_embedding_bench/Dockerfile.bench \
  --build-arg BASE_IMAGE=onyxdotapp/onyx-backend:latest -t onyx-backend:vertex-bench .)

# Write .cache/merged_profiles.json (profiles.json and bench_profiles.json).
python -c "import bench; bench.merged_profiles_file()"

# Start a mock on the host. On Linux, add --host 0.0.0.0 so that the container can reach it.
python mock_vertex.py --port 8799 --profiles .cache/merged_profiles.json --profile unlimited_300ms &

# 1 CPU, 12 GB memory, label "base".
./docker_trial.sh 1 12 base --profile unlimited_300ms --pod-concurrency 6 --duration 90
```

The container mounts the repository and writes to `results_docker.jsonl`. Set `IMAGE`,
`MOCK_PORT` or `PYTHON` to change the defaults of `docker_trial.sh`.

## Profiles

A profile sets the mock limits: `rpm`, `tpm`, `rpd`, `max_concurrency`, inputs
per request, dynamic shared quota (DSQ) contention, transient 503 errors and
latency. [VERTEX_LIMITS.md](VERTEX_LIMITS.md) gives the sources for the values.
`unlimited` and `tiny_rpm` are always available.

The mock checks each request in this order: 400 validation, `max_concurrency`,
`rpm`, `tpm`, `rpd`, DSQ 429, transient 503, then the latency sleep. It
estimates tokens as characters / 4. Use `GET /stats`, `POST /reset` and
`POST /profile/<name>` to control the mock.

## Result fields

Each line of `results.jsonl` has these fields:

| Field | Meaning |
|---|---|
| `status` | `ok`, `oom` (RSS went above `--mem-limit-gb`), `timeout`, `crash(rc=N)`, `worker_error` (a worker could not load a batch or build an embedder) or `all_batches_failed` (no batch finished, and at least one batch raised an exception). `bench.py` exits with 1 when the status is not `ok`. |
| `git` | Commit, branch and a hash of the uncommitted diff outside this directory. |
| `chunk_set` | Fingerprint of the chunk set. |
| `config` | Trial arguments and the Onyx environment. The result keeps the value of an `--env` override only for the defaults and for names that start with `VERTEXAI_`, `INDEXING_EMBEDDING_`, `EMBEDDING_` or `BENCH_`. It shows other values as `<redacted>`. |
| `metrics.steady_inputs_per_min` | Inputs that the provider embedded per minute after `--warmup` seconds. This is the main result. It equals chunks per minute only when `failed_chunks` and `batch_exceptions` are 0. Otherwise it includes inputs that the pipeline sent again or discarded. |
| `metrics.client_avg_in_flight`, `client_peak_in_flight` | Concurrent SDK calls, mean and peak. The mean includes failed calls and calls that did not finish. |
| `metrics.call_latency_p50_s`, `call_latency_p95_s` | SDK call latency. |
| `metrics.pipeline_chunks_ok`, `failed_chunks`, `failed_docs`, `batch_exceptions` | Pipeline results. |
| `metrics.rate_limit_wait_s`, `provider_throttle_wait_s` | Time that threads waited for the rate limiter and after 429 errors. |
| `metrics.peak_rss_gb`, `p95_rss_gb`, `peak_rss_delta_gb` | Memory. `peak_rss_gb` includes setup. The delta is the peak RSS of the trial minus the RSS at the start of the trial. |
| `metrics.cpu_cores_used`, `max_os_threads` | CPU and threads of the Onyx process. |
| `mock` | Mock counters for the trial, without setup traffic: requests, `throttled_429`, `errors_5xx`, `token_requests`, `peak_in_flight`. |

## Limits of the benchmark

- The benchmark does not use Postgres, OpenSearch, Vespa or Redis.
- The admin embedding rate limiter needs Postgres and Redis. `bench.py`
  replaces it with "no limit configured".
- The vector database write is a stub. It only reads the embedded chunks back.
- The mock latency comes from the profile only. Real latency changes with
  region, time and load.
- Each trial measures one pod. The model does not include many pods that share
  one project quota, except through the DSQ contention of a profile.

## Generated files

`.cache/`, `results.jsonl`, `results_docker.jsonl` and `sweep.log` are local.
`.gitignore` excludes them.
