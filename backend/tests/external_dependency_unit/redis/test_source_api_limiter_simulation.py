"""The source-API limiter against a simulated Google, at 40 times speed.

In run R5 on idxbench, the Drive budget was 600 requests a second and Google
accepted about 150 a second, a share of 0.25. The budget made a sawtooth:
it grew from the floor of 0.1 to 0.45-0.65, Google refused a burst, and 3-4
storm cuts in a row took it back to the floor. Group sync starved behind
the conversion threads.

This simulation keeps the shares. Time is 40 times faster: the limiter's
times are 40 times shorter, and Google's minute is 1.5 s. Google accepts at
most its quota in any minute and refuses the rest. A refusal reaches the
caller after the request's latency, so a burst sends refusals after the cut
that it caused.
"""

import collections
import json
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.source_api_limiter import RedisSourceApiLimiter, SourceApiBudget
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import TenantRedisClient, get_redis_client

_API = "drive"
_SPEED = 40.0
# Real seconds for each second of the bench.
_SCALE = 1 / _SPEED
# The budget: 400 requests a second, in windows of 10 bench seconds.
_BUDGET_PER_SECOND = 400
# Google accepts a share of 0.25 of the budget, in any bench minute.
_GOOGLE_SHARE = 0.25
_GOOGLE_MINUTE = 60 * _SCALE
# The time that a request takes, 2 bench seconds.
_LATENCY = 2 * _SCALE
_CONVERSION_THREADS = 32
_RUN_SECONDS = 24.0
# The last part of the run, when the budget must have settled.
_SETTLED_SECONDS = 12.0


class _Google:
    """Accepts at most its quota of requests in any minute."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._accepted: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()
        self.answers: list[tuple[float, bool]] = []

    def send(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._accepted and self._accepted[0] <= now - _GOOGLE_MINUTE:
                self._accepted.popleft()
            accepted = len(self._accepted) < self._per_minute
            if accepted:
                self._accepted.append(now)
            self.answers.append((now, accepted))
        return accepted


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    yield tenant
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


@pytest.fixture
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limiter's times, 40 times shorter."""
    module = redis_rate_window
    for name, seconds in (
        ("REFUSAL_WINDOW_SECONDS", module.REFUSAL_WINDOW_SECONDS),
        ("CUT_HOLD_SECONDS", module.CUT_HOLD_SECONDS),
        ("STORM_RECUT_SECONDS", module.STORM_RECUT_SECONDS),
        ("GROW_INTERVAL_SECONDS", module.GROW_INTERVAL_SECONDS),
    ):
        monkeypatch.setattr(module, name, seconds * _SCALE)


def test_the_budget_settles_near_the_rate_that_google_accepts(
    tenant_id: str, fast_limiter: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = fast_limiter
    budget = SourceApiBudget(
        per_credential=int(_BUDGET_PER_SECOND * 60 * _SCALE),
        period_seconds=60 * _SCALE,
        window_seconds=10 * _SCALE,
        count_requests=True,
    )
    limiter = RedisSourceApiLimiter(
        tenant_id,
        f"google_drive:{uuid4().hex}",
        {_API: budget},
        source=DocumentSource.GOOGLE_DRIVE,
    )
    window = limiter.credential_window(_API)
    assert window is not None
    google = _Google(int(_BUDGET_PER_SECOND * _GOOGLE_SHARE * 60 * _SCALE))

    cuts: list[float] = []
    record_cut = source_api_limiter.record_limiter_cut

    def recording_cut(
        source: str, api: str, scope: source_api_limiter.LimiterScope
    ) -> None:
        cuts.append(time.monotonic())
        record_cut(source, api, scope)

    monkeypatch.setattr(source_api_limiter, "record_limiter_cut", recording_cut)

    started = time.monotonic()
    stop = threading.Event()
    sync_waits: list[float] = []
    conversion_waits: list[float] = []

    def request() -> None:
        accepted = google.send()
        time.sleep(_LATENCY)  # test-flakes: allow the request's latency
        if not accepted:
            limiter.report_rate_limit(_API, None, user_scope=False)

    def conversion() -> None:
        while not stop.is_set():
            asked = time.monotonic()
            limiter.acquire(_API, 1, bulk=True)
            conversion_waits.append(time.monotonic() - asked)
            request()

    def group_sync() -> None:
        # One thread of listing calls, one after the other, as group sync.
        while not stop.is_set():
            asked = time.monotonic()
            limiter.acquire(_API, 1)
            sync_waits.append(time.monotonic() - asked)
            request()

    factors: list[tuple[float, float]] = []
    client = get_redis_client(tenant_id=tenant_id)

    def sample() -> None:
        while not stop.is_set():
            factor = client.hget(f"{window.key}:meta", "factor")
            factors.append(
                (time.monotonic(), float(factor) if factor is not None else 1.0)
            )
            stop.wait(0.05)

    threads = [
        threading.Thread(target=conversion) for _ in range(_CONVERSION_THREADS)
    ] + [threading.Thread(target=group_sync), threading.Thread(target=sample)]
    for thread in threads:
        thread.start()
    # The simulation runs for 16 bench minutes.
    stop.wait(_RUN_SECONDS)
    stop.set()
    for thread in threads:
        thread.join(timeout=30)

    settled_from = started + _RUN_SECONDS - _SETTLED_SECONDS
    settled = [factor for at, factor in factors if at >= settled_from]
    mean = statistics.mean(settled)
    summary = (mean, min(settled), max(settled), [at - started for at in cuts])
    # R5 swung between 0.1 and 0.65 with a mean of 0.19. The budget now stays
    # near Google's share of 0.25.
    assert 0.2 <= mean <= 0.32, summary
    assert min(settled) >= 0.15, summary
    assert max(settled) <= 0.4, summary

    # One burst gives one cut: after the burst at the start, no cut follows
    # another in the same hold.
    settled_cuts = [at for at in cuts if at >= settled_from]
    gaps = [
        later - earlier
        for earlier, later in zip(settled_cuts, settled_cuts[1:], strict=False)
    ]
    assert all(gap >= redis_rate_window.CUT_HOLD_SECONDS for gap in gaps), summary

    answers = [accepted for at, accepted in google.answers if at >= settled_from]
    refused_share = answers.count(False) / len(answers)
    assert refused_share < 0.05, (refused_share, summary)

    # Group sync gets its slots while 32 conversion threads wait for theirs.
    assert len(sync_waits) > 100
    assert statistics.median(sync_waits) < _SCALE, statistics.median(sync_waits)
    assert statistics.mean(sync_waits) * 5 < statistics.mean(conversion_waits), (
        statistics.mean(sync_waits),
        statistics.mean(conversion_waits),
    )


# Run R6 had about 2,000 conversion threads over 12 pods. Each thread held a
# place in the Redis queue and tried again every 1-5 s, and each try read up
# to 2,000 waiters, so the Redis engine ran at 96-100 % CPU. This simulation
# runs 12 pod processes with 2,000 threads in all against the same Redis.
_PODS = 12
_THREADS_PER_POD = 2000 // _PODS
# Google answers in buckets of 10 bench seconds.
_GOOGLE_BUCKET = 10 * _SCALE
_POD_RUN_SECONDS = 20.0
# The pods import the app before they start at the same wall-clock time.
_POD_START_DELAY_SECONDS = 40.0

_POD_SCRIPT = """
import json, sys, threading, time
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.source_api_limiter import RedisSourceApiLimiter, SourceApiBudget
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client

args = json.loads(sys.argv[1])
start_at = args["start_at"]
end_at = start_at + args["run"]
scale = args["scale"]
for name in ("REFUSAL_WINDOW_SECONDS", "CUT_HOLD_SECONDS", "STORM_RECUT_SECONDS",
             "GROW_INTERVAL_SECONDS"):
    setattr(redis_rate_window, name, getattr(redis_rate_window, name) * scale)
budget = SourceApiBudget(
    per_credential=args["per_credential"], period_seconds=60 * scale,
    window_seconds=10 * scale, count_requests=True, start_share=args["start_share"],
)
limiter = RedisSourceApiLimiter(
    args["tenant"], args["credential"], {"drive": budget},
    lambda: time.time() >= end_at, source=DocumentSource.GOOGLE_DRIVE,
)
client = get_redis_client(tenant_id=args["tenant"])
bucket_seconds = args["bucket"]
per_bucket = args["google_per_bucket"]
latency = args["latency"]
sync_waits = []
conversion_waits = []
lock = threading.Lock()

def request():
    bucket = int(time.time() / bucket_seconds)
    accepted = client.incr(f"google:{bucket}") <= per_bucket
    client.incr(f"google:{'ok' if accepted else 'refused'}:{bucket}")
    client.expire(f"google:{bucket}", 120)
    client.expire(f"google:{'ok' if accepted else 'refused'}:{bucket}", 120)
    time.sleep(latency)
    if not accepted:
        limiter.report_rate_limit("drive", None, user_scope=False)

def caller(bulk, waits):
    time.sleep(max(0.0, start_at - time.time()))
    while time.time() < end_at:
        asked = time.monotonic()
        try:
            limiter.acquire("drive", 1, bulk=bulk)
        except ConnectorStopSignal:
            return
        with lock:
            waits.append(time.monotonic() - asked)
        request()

threads = [threading.Thread(target=caller, args=(True, conversion_waits))
           for _ in range(args["threads"])]
if args["with_sync"]:
    threads.append(threading.Thread(target=caller, args=(False, sync_waits)))
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(json.dumps({"sync_waits": sync_waits, "conversion_waits": conversion_waits}))
"""


def test_2000_threads_over_12_pods_keep_the_redis_work_flat(
    tenant_id: str,
) -> None:
    per_credential = int(_BUDGET_PER_SECOND * 60 * _SCALE)
    credential = f"google_drive:{uuid4().hex}"
    limiter = RedisSourceApiLimiter(
        tenant_id,
        credential,
        {
            _API: SourceApiBudget(
                per_credential=per_credential,
                period_seconds=60 * _SCALE,
                window_seconds=10 * _SCALE,
                count_requests=True,
                start_share=0.25,
            )
        },
        source=DocumentSource.GOOGLE_DRIVE,
    )
    window = limiter.credential_window(_API)
    assert window is not None
    client = get_redis_client(tenant_id=tenant_id)
    start_at = time.time() + _POD_START_DELAY_SECONDS
    google_per_bucket = int(_BUDGET_PER_SECOND * _GOOGLE_SHARE * _GOOGLE_BUCKET)
    pods = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _POD_SCRIPT,
                json.dumps(
                    {
                        "scale": _SCALE,
                        "per_credential": per_credential,
                        "start_share": 0.25,
                        "tenant": tenant_id,
                        "credential": credential,
                        "bucket": _GOOGLE_BUCKET,
                        "google_per_bucket": google_per_bucket,
                        "latency": _LATENCY,
                        "start_at": start_at,
                        "run": _POD_RUN_SECONDS,
                        "threads": _THREADS_PER_POD,
                        "with_sync": index == 0,
                    }
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(_PODS)
    ]
    try:
        to_start = max(0.0, start_at - time.time())
        time.sleep(to_start)  # test-flakes: allow the pods start together
        evals_before = _eval_calls(client)
        queued: list[int] = []
        factors: list[tuple[float, float]] = []
        while time.time() < start_at + _POD_RUN_SECONDS:
            queued.append(client.zcard(f"{window.key}:queue"))
            factor = client.hget(f"{window.key}:meta", "factor")
            factors.append((time.time(), float(factor) if factor else 0.0))
            time.sleep(0.05)  # test-flakes: allow the sampling interval
        evals = _eval_calls(client) - evals_before
        outputs = [pod.communicate(timeout=120) for pod in pods]
    finally:
        for pod in pods:
            if pod.poll() is None:
                pod.kill()
    for pod, (_, stderr) in zip(pods, outputs, strict=True):
        assert pod.returncode == 0, stderr[-3000:]
    results = [json.loads(stdout.strip().splitlines()[-1]) for stdout, _ in outputs]
    conversion_waits = [w for r in results for w in r["conversion_waits"]]
    sync_waits = [w for r in results for w in r["sync_waits"]]

    google_ok, google_refused = _google_answers(client, start_at)
    taken_per_second = len(conversion_waits) / _POD_RUN_SECONDS
    summary = {
        "max_queued": max(queued),
        "evals_per_second": evals / _POD_RUN_SECONDS,
        "taken_per_second": taken_per_second,
        "google_ok": google_ok,
        "google_refused": google_refused,
    }

    # About one Redis waiter for each pod and class, not one for each thread.
    assert max(queued) <= 2 * _PODS, summary
    # The script runs stay a small multiple of the slots taken. In R6 each
    # of 2,000 waiters tried every 1-5 s.
    assert evals / _POD_RUN_SECONDS <= 5 * taken_per_second + 50, summary

    # The old behaviours hold. The budget settles near Google's share.
    settled_from = start_at + _POD_RUN_SECONDS / 2
    settled = [factor for at, factor in factors if at >= settled_from]
    assert 0.18 <= statistics.mean(settled) <= 0.36, (statistics.mean(settled), summary)
    # No start storm: the run starts at a quarter of the budget.
    assert google_refused <= 0.1 * (google_ok + google_refused), summary
    # Group sync gets its slots while 2,000 conversion threads wait.
    assert len(sync_waits) > 20, summary
    assert statistics.median(sync_waits) < 5 * _SCALE, statistics.median(sync_waits)


def _eval_calls(client: TenantRedisClient) -> int:
    """The scripts that the test Redis ran, for all clients."""
    stats = client.info("commandstats")
    return sum(
        int(stats.get(name, {}).get("calls", 0))
        for name in ("cmdstat_eval", "cmdstat_evalsha")
    )


def _google_answers(client: TenantRedisClient, start_at: float) -> tuple[int, int]:
    """The requests that the simulated Google accepted and refused."""
    ok = refused = 0
    first = int(start_at / _GOOGLE_BUCKET)
    last = int((start_at + _POD_RUN_SECONDS) / _GOOGLE_BUCKET) + 1
    for bucket in range(first, last + 1):
        ok += int(client.get(f"google:ok:{bucket}") or 0)
        refused += int(client.get(f"google:refused:{bucket}") or 0)
    return ok, refused
