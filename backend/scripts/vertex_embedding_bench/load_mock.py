"""Raw httpx load against mock_vertex, to check the mock is not the bottleneck.

    python load_mock.py --concurrency 500 --duration 10 --procs 4

Sends gemini-embedding-2 `:embedContent` requests (3072 dims) from `--procs`
processes, each with `concurrency/procs` workers on one httpx.AsyncClient.
"""

from __future__ import annotations

import argparse
import asyncio
import multiprocessing as mp
import time

import httpx

PATH = "v1beta1/projects/mock-project/locations/us-central1/publishers/google/models/gemini-embedding-2:embedContent"
BODY = {
    "content": {
        "parts": [
            {
                "text": "task: search result | query: "
                + "lorem ipsum dolor sit amet " * 20
            }
        ]
    },
    "embedContentConfig": {"outputDimensionality": 3072, "autoTruncate": True},
}


async def _run(
    base: str, conc: int, duration: float
) -> tuple[int, int, int, list[float], dict[str, int]]:
    limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
    ok = err = nbytes = 0
    lats: list[float] = []
    errs: dict[str, int] = {}
    async with httpx.AsyncClient(
        base_url=base, limits=limits, timeout=60, headers={"Authorization": "Bearer x"}
    ) as c:
        end = time.perf_counter() + duration

        async def worker(i: int) -> None:
            nonlocal ok, err, nbytes
            # Stagger connects: macOS somaxconn defaults to 128 and drops SYN bursts.
            await asyncio.sleep(i * 0.004)
            while time.perf_counter() < end:
                t0 = time.perf_counter()
                try:
                    r = await c.post(PATH, json=BODY)
                    if r.status_code == 200:
                        ok += 1
                        nbytes += len(r.content)
                    else:
                        err += 1
                except Exception as e:
                    err += 1
                    errs[type(e).__name__] = errs.get(type(e).__name__, 0) + 1
                lats.append(time.perf_counter() - t0)

        await asyncio.gather(*(worker(i) for i in range(conc)))
    return ok, err, nbytes, lats, errs


def _proc(
    args: tuple[str, int, float],
) -> tuple[int, int, int, list[float], dict[str, int]]:
    return asyncio.run(_run(*args))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8799/")
    ap.add_argument("--concurrency", type=int, default=500)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()

    httpx.post(a.base_url.rstrip("/") + "/reset", timeout=10)
    per = max(1, a.concurrency // a.procs)
    t0 = time.perf_counter()
    with mp.Pool(a.procs) as pool:
        results = pool.map(_proc, [(a.base_url, per, a.duration)] * a.procs)
    wall = time.perf_counter() - t0
    ok = sum(r[0] for r in results)
    err = sum(r[1] for r in results)
    nbytes = sum(r[2] for r in results)
    lats = sorted(x for r in results for x in r[3])
    errs: dict[str, int] = {}
    for r in results:
        for k, v in r[4].items():
            errs[k] = errs.get(k, 0) + v
    stats = httpx.get(a.base_url.rstrip("/") + "/stats", timeout=10).json()
    pct = lambda q: lats[min(len(lats) - 1, int(q * len(lats)))] * 1000 if lats else 0  # noqa: E731
    print(
        f"concurrency={per * a.procs} procs={a.procs} duration={a.duration}s ok={ok} err={err} "
        f"client_rps={ok / a.duration:.0f} avg_body={nbytes / max(ok, 1) / 1024:.1f}KiB "
        f"p50={pct(0.5):.1f}ms p99={pct(0.99):.1f}ms wall={wall:.1f}s errors={errs}"
    )
    secs = [x for x in stats["ok_per_second_last_120s"] if x > 0]
    steady = sorted(secs[2:-1]) if len(secs) > 4 else secs
    med = steady[len(steady) // 2] if steady else 0
    print(
        f"server: ok={stats['ok']} peak_in_flight={stats['peak_in_flight']} "
        f"steady_median_rps={med} per_sec={secs}"
    )


if __name__ == "__main__":
    main()
