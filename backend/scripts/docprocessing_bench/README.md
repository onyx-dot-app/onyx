# Docprocessing benchmark

Measures the throughput of docprocessing: the path from a staged document batch to chunks
in the index. It also checks that the index and Postgres hold the correct result, so a
faster build that writes something different fails.

Use it to compare two builds on one machine. The corpus is synthetic, so the numbers do
not predict a customer's corpus.

## What runs

| Part | Real or mock |
| --- | --- |
| Connector and docfetching | Replaced. A seeded generator stages batches through `DocumentBatchStorage` |
| `_docprocessing_task`, chunker, adapter, coordination | Real. One thread per Celery worker thread |
| Postgres, Redis, file store, OpenSearch | Real |
| Embedding | Mock model server (`tests/integration/mock_services/mock_model_server`) |
| LLM enrichment | Off |

The run uses its own Postgres database (`docproc_bench_db`), OpenSearch index
(`docproc_bench_index`), file store bucket (`docproc-bench-file-store`) and Redis database
(9). Setup drops and creates them on each run. The worker refuses a database or index name
without the `docproc_bench` prefix, and a file store that is not the S3 backend with a
`docproc-bench` bucket.

The mock model server returns a vector that is a pure function of the text. Two runs over
one corpus therefore write the same index.

## Run it

The services of a dev stack must be up (`ods` or docker compose).

```bash
cd backend
uv run python -m scripts.benchmark_docprocessing --profile mixed --json-out report.json
```

| Option | Use |
| --- | --- |
| `--profile` | `small` (1-5k characters), `mixed` (long tail, the default), `large` (1-8 MB), `pathological` (16 documents of 20 MB) |
| `--docs`, `--doc-chars`, `--seed` | Change the corpus. Each combination is a different corpus id. The default is 400 `mixed` documents |
| `--passes` | `first` (all new), `unchanged` (same corpus again), `updated` (1 document in 10 changed, to half its size) |
| `--threads` | Worker threads. The default 6 is the default worker concurrency |
| `--latency` | Embed latency of the mock: `zero`, `local` or `api` |
| `--poison-docs` | Documents that the mock refuses to embed |
| `--max-rss-mb` | Fail when peak RSS is above this |
| `--update-golden` | Store the digests of this run as the expected values |
| `--cprofile` | Write a cProfile to `profiles/<pass>.prof`. The run then uses one worker thread, because Python allows one active profiler. Do not compare its timings |

### With the limits of the pod

Run the measured phase in a backend image with a CPU and memory limit. The source tree is
mounted over `/app`, so the image only supplies the dependencies.

```bash
uv run python -m scripts.benchmark_docprocessing --profile mixed \
    --container-image <backend image> --container-network <compose network> \
    --container-memory 12g --container-cpus 1
```

The defaults are the helm limits of `celery_worker_docprocessing`. When the kernel kills the
worker for memory, the run fails the gate `worker not killed (OOM)`. Use
`--container-env KEY=VALUE` when the service names differ from the compose names.

## Gates

The exit status is 1 when a gate fails.

| Gate | Catches |
| --- | --- |
| All batches complete | A batch that raised, or a completion count that is wrong |
| No missing or unexpected document | Lost documents, or documents that must have failed |
| No duplicate chunk, no gap in chunk indexes | A broken write, or stale chunks after an update |
| Postgres `chunk_count` equals the index | Postgres and the index out of step |
| Every indexed document has a content hash | A change that breaks the dedup gate |
| One error row per poisoned document | A failure that takes other documents with it, or is not recorded |
| Unchanged corpus embeds nothing | A broken dedup gate |
| Unchanged corpus leaves the index as it was | A rewrite of unchanged documents |
| Index and Postgres digests equal golden | Any change to chunk content, vectors, ACLs or metadata |
| Worker not killed (OOM) | Memory above the container limit |
| Peak RSS within the budget | Memory growth below the limit (`--max-rss-mb`) |

The golden values are in `golden.json`, one entry per corpus id, pass, embedding model and
multipass setting. A change that alters chunk content on purpose must update them with
`--update-golden` in the same commit.

`golden.json` has values for the default corpus and a few others. A corpus with no entry
fails the golden gate. To compare two builds on such a corpus, run the base build with
`--update-golden` first.

## Read the report

- **docs/min and chunks/min** cover the time from the first batch start to the last batch
  end. Compare chunks/min too, so a change in chunk count does not look like a gain.
- **CPU cores** near 1.0 means the worker is limited by the GIL, not by a service.
- **Stages** come from `index_attempt_stage_metric`. The times are wall time per batch, so
  with 6 threads on one core they include the wait for the GIL.
- **Timings are not valid** when the host swaps. The run refuses to start above
  `--max-swap-pct` unless `--allow-swap` is set; the gates stay valid in that case.

Run each configuration three times and compare medians.

One run holds a machine-wide lock. A second run waits for it, because both use the same
database and index and would change each other's timings.

## Latency profiles

`zero` shows the limit of Onyx's own code. `local` and `api` are estimates. To calibrate
one, time real embed requests of several batch sizes and text lengths, fit base, per-text
and per-1000-character costs, and change `_LATENCY_PROFILES`.

## Mock model server

`PATCH /_mock/config` changes the vector dimension, the latency and the faults.
`GET /_mock/stats` returns the request, text and character counts, and the peak number of
requests in flight. `POST /_mock/reset-stats` clears them.
