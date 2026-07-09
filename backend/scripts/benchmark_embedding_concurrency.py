"""Benchmark concurrent local-model embedding throughput on a model server.

Reproduces the request pattern the indexing pipeline sends to the indexing model
server: N client threads (INDEXING_EMBEDDING_MODEL_NUM_THREADS defaults to 8) each
POSTing batches of passage texts to /encoder/bi-encoder-embed, mirroring
onyx.natural_language_processing.search_nlp_models._batch_encode_texts.

Usage (against a dedicated CPU-only server so results aren't polluted):

    INDEXING_ONLY=True uvicorn model_server.main:app --port 9001 &
    python scripts/benchmark_embedding_concurrency.py --url http://localhost:9001

Compare runs by restarting the server with different code / env (e.g.
LOCAL_EMBEDDING_MAX_CONCURRENCY) between invocations.
"""

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

EMBED_ENDPOINT = "/encoder/bi-encoder-embed"

# ~450 tokens once tokenized -- near the 512-token max_context_length of typical
# local embedding models, matching real indexing chunks.
_WORDS_PER_TEXT = 300


def _make_texts(num_texts: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    vocab = [
        "".join(
            rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 10))
        )
        for _ in range(2000)
    ]
    return [
        " ".join(rng.choice(vocab) for _ in range(_WORDS_PER_TEXT))
        for _ in range(num_texts)
    ]


def _embed_once(
    url: str, texts: list[str], model_name: str, max_context_length: int
) -> float:
    payload = {
        "texts": texts,
        "model_name": model_name,
        "max_context_length": max_context_length,
        "normalize_embeddings": True,
        "text_type": "passage",
    }
    start = time.monotonic()
    response = requests.post(url + EMBED_ENDPOINT, json=payload, timeout=600)
    response.raise_for_status()
    return time.monotonic() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:9001")
    parser.add_argument("--model-name", default="nomic-ai/nomic-embed-text-v1")
    parser.add_argument("--max-context-length", type=int, default=512)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Concurrent client threads (indexing default: "
        "INDEXING_EMBEDDING_MODEL_NUM_THREADS=8)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=48,
        help="Total embed requests to send",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Texts per request (indexing default: BATCH_SIZE_ENCODE_CHUNKS=8)",
    )
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    texts = _make_texts(args.batch_size, args.seed)

    # Warm up: loads the model and pre-warms caches; excluded from measurement.
    print(f"Warming up {args.model_name} at {args.url} ...", file=sys.stderr)
    warmup_s = _embed_once(
        args.url, texts[:1], args.model_name, args.max_context_length
    )
    print(f"Warmup done in {warmup_s:.2f}s", file=sys.stderr)

    print(
        f"Benchmarking: {args.requests} requests x {args.batch_size} texts, "
        f"{args.concurrency} concurrent clients",
        file=sys.stderr,
    )

    def _one_request(_request_idx: int) -> float:
        return _embed_once(args.url, texts, args.model_name, args.max_context_length)

    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        latencies = list(pool.map(_one_request, range(args.requests)))
    wall_s = time.monotonic() - wall_start

    latencies.sort()
    total_texts = args.requests * args.batch_size
    results = {
        "concurrency": args.concurrency,
        "requests": args.requests,
        "batch_size": args.batch_size,
        "wall_clock_s": round(wall_s, 2),
        "throughput_texts_per_s": round(total_texts / wall_s, 2),
        "latency_mean_s": round(statistics.mean(latencies), 2),
        "latency_p50_s": round(latencies[len(latencies) // 2], 2),
        "latency_p95_s": round(latencies[int(len(latencies) * 0.95) - 1], 2),
        "latency_max_s": round(latencies[-1], 2),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
