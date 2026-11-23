"""Mock Google Vertex AI embedding server for load tests.

Implements the two Vertex embedding endpoints that google-genai uses for
`client.aio.models.embed_content(...)` with `vertexai=True`:

- `POST .../publishers/google/models/<gemini-embedding-2*>:embedContent`
  (one `content` per request; every `gemini*` model except gemini-embedding-001)
- `POST .../publishers/google/models/<model>:predict` with `instances[]`
  (gemini-embedding-001, text-embedding-*, text-multilingual-embedding-*)

It also mocks the OAuth token endpoint (`POST /token`) for service-account
JWT-bearer exchange, so a fake SA JSON whose `token_uri` points here works with
google-auth unchanged.

Run:
    python mock_vertex.py --write-sa .cache/mock-sa.json --port 8799
    python mock_vertex.py --port 8799 --profile unlimited
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

try:
    import orjson

    def _loads(data: bytes) -> Any:
        return orjson.loads(data)

    def _dumps(obj: Any) -> bytes:
        return orjson.dumps(obj)

except ImportError:  # pragma: no cover

    def _loads(data: bytes) -> Any:
        return json.loads(data)

    def _dumps(obj: Any) -> bytes:
        return json.dumps(obj, separators=(",", ":")).encode()


from fastapi import FastAPI, Request
from fastapi.responses import Response

HERE = Path(__file__).resolve().parent

# Exact body the real Vertex API returns on quota exhaustion.
BODY_429 = (
    b'{"error":{"code":429,"message":"Resource exhausted. Please try again later. '
    b"Please refer to https://cloud.google.com/vertex-ai/generative-ai/docs/error-code-429 "
    b'for more details.","status":"RESOURCE_EXHAUSTED"}}'
)
BODY_503 = (
    b'{"error":{"code":503,"message":"The service is currently unavailable.",'
    b'"status":"UNAVAILABLE"}}'
)
JSON_HEADERS = {"content-type": "application/json; charset=UTF-8"}

N_VECTOR_VARIANTS = 16


def _error(code: int, status: str, message: str) -> Response:
    body = _dumps({"error": {"code": code, "message": message, "status": status}})
    return Response(content=body, status_code=code, headers=JSON_HEADERS)


def _err(code: int, status: str, message: str) -> tuple[int, bytes]:
    return code, _dumps({"error": {"code": code, "message": message, "status": status}})


def _json(obj: Any, code: int = 200) -> Response:
    return Response(content=_dumps(obj), status_code=code, headers=JSON_HEADERS)


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------


@dataclass
class Profile:
    name: str
    description: str = ""
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    max_concurrency: int | None = None
    max_inputs_per_request: int = 250
    max_input_tokens: int = 8192
    dsq: dict[str, float] | None = None
    latency: dict[str, float] = field(
        default_factory=lambda: {
            "base_ms": 0.0,
            "per_1k_tokens_ms": 0.0,
            "jitter_sigma": 0.0,
        }
    )
    transient_error_rate: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> "Profile":
        lat = {"base_ms": 0.0, "per_1k_tokens_ms": 0.0, "jitter_sigma": 0.0}
        lat.update(d.get("latency") or {})
        return cls(
            name=name,
            description=d.get("description", ""),
            rpm=d.get("rpm"),
            tpm=d.get("tpm"),
            rpd=d.get("rpd"),
            max_concurrency=d.get("max_concurrency"),
            max_inputs_per_request=int(d.get("max_inputs_per_request") or 250),
            max_input_tokens=int(d.get("max_input_tokens") or 8192),
            dsq=d.get("dsq"),
            latency=lat,
            transient_error_rate=float(d.get("transient_error_rate") or 0.0),
            raw=d,
        )


# Always available, even when the profiles file lacks them (smoke tests rely on these).
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "unlimited": {
        "description": "built-in: no limits, no errors, no latency",
        "max_inputs_per_request": 250,
    },
    "tiny_rpm": {
        "description": "built-in: 5 requests/min, for 429 smoke tests",
        "rpm": 5,
        "max_inputs_per_request": 250,
        "latency": {"base_ms": 5.0},
    },
}


def load_profiles(path: str | None) -> tuple[dict[str, Profile], str]:
    candidates = (
        [Path(path)]
        if path
        else [HERE / "profiles.json", HERE / "profiles.default.json"]
    )
    for p in candidates:
        if p.exists():
            data = json.loads(p.read_text())
            profiles = {
                k: Profile.from_dict(k, v)
                for k, v in data.items()
                if isinstance(v, dict) and not k.startswith("_")
            }
            for name, d in BUILTIN_PROFILES.items():
                profiles.setdefault(name, Profile.from_dict(name, d))
            return profiles, str(p)
    raise SystemExit(f"no profiles file found in {candidates}")


# --------------------------------------------------------------------------
# Precomputed vectors
# --------------------------------------------------------------------------


class VectorCache:
    """Serialized JSON arrays of realistic unit-norm float vectors, per dimension."""

    def __init__(self, seed: int) -> None:
        self._seed = seed
        self._cache: dict[int, list[bytes]] = {}

    def get(self, dim: int, idx: int) -> bytes:
        variants = self._cache.get(dim)
        if variants is None:
            rng = random.Random(self._seed * 1_000_003 + dim)
            variants = []
            for _ in range(N_VECTOR_VARIANTS):
                vals = [rng.gauss(0.0, 1.0) for _ in range(dim)]
                norm = math.sqrt(sum(v * v for v in vals)) or 1.0
                # ~9 significant digits, like the real API ("-0.012345678").
                variants.append(
                    (
                        "[" + ",".join(format(v / norm, ".9g") for v in vals) + "]"
                    ).encode()
                )
            self._cache[dim] = variants
        return variants[idx % N_VECTOR_VARIANTS]


# --------------------------------------------------------------------------
# State / limiter
# --------------------------------------------------------------------------


class SecondRing:
    """Counts per wall-clock second for the last `size` seconds."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.counts = [0] * size
        self.secs = [-1] * size

    def add(self, now: float, n: int = 1) -> None:
        s = int(now)
        i = s % self.size
        if self.secs[i] != s:
            self.secs[i] = s
            self.counts[i] = 0
        self.counts[i] += n

    def window(self, now: float, seconds: int) -> list[int]:
        """Counts for the last `seconds` full seconds before the current one, oldest first."""
        s = int(now)
        out = []
        for t in range(s - seconds, s):
            i = t % self.size
            out.append(self.counts[i] if self.secs[i] == t else 0)
        return out

    def sum_last(self, now: float, seconds: int) -> int:
        s = int(now)
        total = 0
        for t in range(s - seconds + 1, s + 1):
            i = t % self.size
            if self.secs[i] == t:
                total += self.counts[i]
        return total


class State:
    def __init__(self, profile: Profile, latency_scale: float, seed: int) -> None:
        self.profile = profile
        self.latency_scale = latency_scale
        self.rng = random.Random(seed)
        # Requests can outlive a reset, so reset() keeps this count.
        self.in_flight = 0
        self.generation = 0
        self.reset()

    def reset(self) -> None:
        # Requests that started before the reset do not count in the new trial.
        self.generation += 1
        self.started = time.time()
        self.requests = 0
        self.ok = 0
        self.throttled_429 = 0
        self.throttle_reasons: collections.Counter[str] = collections.Counter()
        self.errors_5xx = 0
        self.bad_request_400 = 0
        self.unauthenticated_401 = 0
        self.inputs = 0
        self.input_tokens = 0
        self.token_requests = 0
        self.peak_in_flight = self.in_flight
        self.by_endpoint: collections.Counter[str] = collections.Counter()
        # Admitted requests (counted against quota) and their tokens.
        self.req_window: collections.deque[float] = collections.deque()
        self.tok_window: collections.deque[tuple[float, int]] = collections.deque()
        self.tok_window_sum = 0
        self.day_window: collections.deque[list[float]] = (
            collections.deque()
        )  # [minute, count]
        self.day_sum = 0
        # All arriving requests per second (drives DSQ contention), ok per second.
        self.arrivals = SecondRing(180)
        self.ok_per_sec = SecondRing(180)
        self.ok_window: collections.deque[float] = collections.deque()

    def _trim(self, now: float) -> None:
        cutoff = now - 60.0
        rw = self.req_window
        while rw and rw[0] <= cutoff:
            rw.popleft()
        tw = self.tok_window
        while tw and tw[0][0] <= cutoff:
            self.tok_window_sum -= tw.popleft()[1]
        dcut = (now - 86400.0) // 60
        dw = self.day_window
        while dw and dw[0][0] <= dcut:
            self.day_sum -= int(dw.popleft()[1])
        ow = self.ok_window
        while ow and ow[0] <= cutoff:
            ow.popleft()

    def admit(self, now: float, tokens: int) -> str | None:
        """Returns a throttle reason, or None when the request may proceed."""
        p = self.profile
        self._trim(now)
        if p.max_concurrency is not None and self.in_flight >= p.max_concurrency:
            return "concurrency"
        if p.rpm is not None and len(self.req_window) >= p.rpm:
            return "rpm"
        if p.tpm is not None and self.tok_window_sum + tokens > p.tpm:
            return "tpm"
        if p.rpd is not None and self.day_sum >= p.rpd:
            return "rpd"
        if p.dsq:
            rps = self.arrivals.sum_last(now, 5) / 5.0
            prob = float(p.dsq.get("base_429_prob", 0.0)) + float(
                p.dsq.get("slope", 0.0)
            ) * max(0.0, rps - float(p.dsq.get("load_threshold_rps", 0.0)))
            prob = min(prob, float(p.dsq.get("max_prob", 0.95)))
            if prob > 0 and self.rng.random() < prob:
                return "dsq"
        # Admitted: count against quota windows.
        self.req_window.append(now)
        self.tok_window.append((now, tokens))
        self.tok_window_sum += tokens
        minute = now // 60
        if self.day_window and self.day_window[-1][0] == minute:
            self.day_window[-1][1] += 1
        else:
            self.day_window.append([minute, 1])
        self.day_sum += 1
        return None

    def latency_s(self, tokens: int) -> float:
        if self.latency_scale <= 0:
            return 0.0
        lat = self.profile.latency
        ms = (
            float(lat.get("base_ms", 0.0))
            + float(lat.get("per_1k_tokens_ms", 0.0)) * tokens / 1000.0
        )
        sigma = float(lat.get("jitter_sigma", 0.0))
        if sigma > 0:
            # Lognormal multiplier with median 1.
            ms *= math.exp(self.rng.gauss(0.0, sigma))
        return max(0.0, ms * self.latency_scale / 1000.0)


# --------------------------------------------------------------------------
# Request parsing helpers
# --------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    # Gemini tokenizers average ~4 chars/token for English prose.
    return max(1, (len(text) + 3) // 4)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        parts = content.get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return ""


def _model_from_path(path: str) -> tuple[str, str]:
    """`v1beta1/projects/p/locations/l/publishers/google/models/m:verb` -> (m, verb)."""
    last = path.rsplit("/", 1)[-1]
    model, _, verb = last.partition(":")
    return model, verb


def _default_dim(model: str) -> int:
    return 3072 if model.startswith("gemini") else 768


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------


class _Reject(Exception):
    """A 400 response, raised by request parsing."""

    def __init__(self, code: int, status: str, message: str) -> None:
        super().__init__(message)
        self.response = _err(code, status, message)


def _parse_inputs(
    st: State, model: str, verb: str, body: Any
) -> tuple[dict[str, Any], list[str]]:
    """Returns (config, input texts). Raises _Reject for a bad request."""
    p = st.profile
    is_embed2 = model.startswith("gemini-embedding-2")
    if verb == "embedContent":
        if "content" not in body or any(
            k in body for k in ("contents", "instances", "requests")
        ):
            st.bad_request_400 += 1
            raise _Reject(
                400,
                "INVALID_ARGUMENT",
                f"Unable to submit request because {model} supports only 1 input per request "
                "(a single `content`). Send one request per input.",
            )
        cfg = body.get("embedContentConfig") or {}
        texts = [_content_text(body["content"])]
    else:
        instances = body.get("instances")
        if not isinstance(instances, list) or not instances:
            st.bad_request_400 += 1
            raise _Reject(
                400,
                "INVALID_ARGUMENT",
                "Request contains an invalid argument: `instances` is empty.",
            )
        cfg = body.get("parameters") or {}
        texts = [
            _content_text(i.get("content")) for i in instances if isinstance(i, dict)
        ]
        limit = 1 if is_embed2 else p.max_inputs_per_request
        if len(texts) > limit:
            st.bad_request_400 += 1
            raise _Reject(
                400,
                "INVALID_ARGUMENT",
                f"Unable to submit request because the input has {len(texts)} instances, "
                f"but {model} supports at most {limit} instance(s) per request.",
            )
    return cfg, texts


def _render(
    vectors: VectorCache,
    verb: str,
    dim: int,
    seed: int,
    texts: list[str],
    tok_counts: list[int],
    truncated: list[bool],
) -> bytes:
    if verb == "embedContent":
        n = tok_counts[0]
        out = b"".join(
            (
                b'{"embedding":{"values":',
                vectors.get(dim, seed),
                b'},"usageMetadata":{"promptTokenCount":',
                str(n).encode(),
                b',"totalTokenCount":',
                str(n).encode(),
                b',"promptTokensDetails":[{"modality":"TEXT","tokenCount":',
                str(n).encode(),
                b"}]}",
                b',"truncated":true}' if truncated[0] else b"}",
            )
        )
    else:
        preds = []
        for i, n in enumerate(tok_counts):
            preds.append(
                b'{"embeddings":{"statistics":{"truncated":'
                + (b"true" if truncated[i] else b"false")
                + b',"token_count":'
                + str(n).encode()
                + b'},"values":'
                + vectors.get(dim, seed + i)
                + b"}}"
            )
        billable = sum(len(t) for t in texts)
        out = (
            b'{"predictions":['
            + b",".join(preds)
            + b'],"metadata":{"billableCharacterCount":'
            + str(billable).encode()
            + b"}}"
        )
    return out


async def handle_model_call(
    st: State, vectors: VectorCache, full_path: str, auth: str, raw_body: bytes
) -> tuple[int, bytes]:
    """Serves one `:embedContent` or `:predict` call. Returns (status, body)."""
    model, verb = _model_from_path(full_path)
    if verb not in ("embedContent", "predict"):
        return _err(404, "NOT_FOUND", f"mock does not implement {full_path!r}")
    st.requests += 1
    st.by_endpoint[verb] += 1
    now = time.time()
    st.arrivals.add(now)

    if not auth.startswith("Bearer "):
        st.unauthenticated_401 += 1
        return _err(
            401,
            "UNAUTHENTICATED",
            "Request is missing required authentication credential. Expected OAuth 2 access token.",
        )

    try:
        body = _loads(raw_body)
    except Exception:
        st.bad_request_400 += 1
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")

    p = st.profile
    try:
        cfg, texts = _parse_inputs(st, model, verb, body)
    except _Reject as e:
        return e.response

    auto_truncate = cfg.get("autoTruncate", True)
    dim = int(cfg.get("outputDimensionality") or _default_dim(model))
    if dim < 1 or dim > 3072:
        st.bad_request_400 += 1
        return _err(
            400,
            "INVALID_ARGUMENT",
            f"outputDimensionality must be in [1, 3072], got {dim}.",
        )

    tok_counts: list[int] = []
    truncated: list[bool] = []
    for t in texts:
        n = estimate_tokens(t)
        if n > p.max_input_tokens:
            if not auto_truncate:
                st.bad_request_400 += 1
                return _err(
                    400,
                    "INVALID_ARGUMENT",
                    f"Unable to submit request because the input token count is {n} but the "
                    f"model supports up to {p.max_input_tokens}.",
                )
            n = p.max_input_tokens
            truncated.append(True)
        else:
            truncated.append(False)
        tok_counts.append(n)
    total_tokens = sum(tok_counts)

    reason = st.admit(now, total_tokens)
    if reason is not None:
        st.throttled_429 += 1
        st.throttle_reasons[reason] += 1
        return 429, BODY_429
    if p.transient_error_rate > 0 and st.rng.random() < p.transient_error_rate:
        st.errors_5xx += 1
        return 503, BODY_503

    generation = st.generation
    st.in_flight += 1
    if st.in_flight > st.peak_in_flight:
        st.peak_in_flight = st.in_flight
    try:
        delay = st.latency_s(total_tokens)
        if delay > 0:
            await asyncio.sleep(delay)
    finally:
        st.in_flight -= 1

    if generation == st.generation:
        st.ok += 1
        st.inputs += len(texts)
        st.input_tokens += total_tokens
        done = time.time()
        st.ok_per_sec.add(done)
        st.ok_window.append(done)

    return 200, _render(vectors, verb, dim, st.requests, texts, tok_counts, truncated)


def build_app(
    profiles: dict[str, Profile], profiles_path: str, state: State, vectors: VectorCache
) -> FastAPI:
    app = FastAPI(title="mock-vertex", docs_url=None, redoc_url=None, openapi_url=None)
    st = state

    @app.get("/healthz")
    async def healthz() -> Response:
        return _json({"ok": True, "profile": st.profile.name})

    @app.get("/stats")
    async def stats() -> Response:
        now = time.time()
        st._trim(now)
        return _json(
            {
                "profile": st.profile.name,
                "latency_scale": st.latency_scale,
                "uptime_s": round(now - st.started, 3),
                "requests": st.requests,
                "ok": st.ok,
                "throttled_429": st.throttled_429,
                "throttle_reasons": dict(st.throttle_reasons),
                "errors_5xx": st.errors_5xx,
                "bad_request_400": st.bad_request_400,
                "unauthenticated_401": st.unauthenticated_401,
                "inputs": st.inputs,
                "input_tokens": st.input_tokens,
                "token_requests": st.token_requests,
                "in_flight": st.in_flight,
                "peak_in_flight": st.peak_in_flight,
                "by_endpoint": dict(st.by_endpoint),
                "achieved_rpm_last_60s": len(st.ok_window),
                "admitted_rpm_last_60s": len(st.req_window),
                "tokens_last_60s": st.tok_window_sum,
                "requests_last_24h": st.day_sum,
                "ok_per_second_last_120s": st.ok_per_sec.window(now, 120),
            }
        )

    @app.post("/reset")
    async def reset() -> Response:
        st.reset()
        return _json({"ok": True, "profile": st.profile.name})

    @app.get("/profiles")
    async def list_profiles() -> Response:
        return _json(
            {
                "source": profiles_path,
                "active": st.profile.name,
                "profiles": {
                    k: v.raw or {"description": v.description}
                    for k, v in profiles.items()
                },
            }
        )

    @app.post("/profile/{name}")
    async def set_profile(name: str, request: Request) -> Response:
        if name not in profiles:
            return _error(
                404, "NOT_FOUND", f"unknown profile {name!r}; have {sorted(profiles)}"
            )
        st.profile = profiles[name]
        scale = request.query_params.get("latency_scale")
        if scale is not None:
            st.latency_scale = float(scale)
        return _json({"ok": True, "profile": name, "latency_scale": st.latency_scale})

    @app.post("/token")
    async def token(request: Request) -> Response:
        body = await request.body()
        form = parse_qs(body.decode("utf-8", "replace"))
        grant = (form.get("grant_type") or [""])[0]
        if grant != "urn:ietf:params:oauth:grant-type:jwt-bearer" or not form.get(
            "assertion"
        ):
            return _json(
                {
                    "error": "invalid_grant",
                    "error_description": f"unsupported grant_type {grant!r}",
                },
                400,
            )
        st.token_requests += 1
        tok = "ya29.mock-" + base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip(
            "="
        )
        return _json({"access_token": tok, "expires_in": 3599, "token_type": "Bearer"})

    async def handle_model(
        full_path: str, auth: str, raw_body: bytes
    ) -> tuple[int, bytes]:
        return await handle_model_call(st, vectors, full_path, auth, raw_body)

    @app.post("/{full_path:path}")
    async def model_call(full_path: str, request: Request) -> Response:
        code, out = await handle_model(
            full_path, request.headers.get("authorization", ""), await request.body()
        )
        return Response(content=out, status_code=code, headers=JSON_HEADERS)

    app.state.handle_model = handle_model
    return app


_RAW_HEADERS = [(b"content-type", b"application/json; charset=UTF-8")]


def fast_path(app: FastAPI) -> Any:
    """ASGI wrapper that serves the embedding endpoints without FastAPI routing.

    Starlette's router/Request/Response add noticeable CPU per request; at a few
    thousand req/s that overhead matters, so the hot path talks ASGI directly.
    """
    handle = app.state.handle_model

    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] == "POST":
            path: str = scope["path"]
            if path.endswith((":embedContent", ":predict")):
                chunks = []
                more = True
                while more:
                    msg = await receive()
                    chunks.append(msg.get("body", b""))
                    more = msg.get("more_body", False)
                auth = ""
                for k, v in scope["headers"]:
                    if k == b"authorization":
                        auth = v.decode("latin-1")
                        break
                code, out = await handle(path.lstrip("/"), auth, b"".join(chunks))
                await send(
                    {
                        "type": "http.response.start",
                        "status": code,
                        "headers": _RAW_HEADERS
                        + [(b"content-length", str(len(out)).encode())],
                    }
                )
                await send({"type": "http.response.body", "body": out})
                return
        await app(scope, receive, send)

    return asgi


# --------------------------------------------------------------------------
# Fake service account
# --------------------------------------------------------------------------


def write_service_account(path: str, port: int, host: str = "127.0.0.1") -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    email = "mock-embedder@mock-project.iam.gserviceaccount.com"
    sa = {
        "type": "service_account",
        "project_id": "mock-project",
        "private_key_id": os.urandom(20).hex(),
        "private_key": pem,
        "client_email": email,
        "client_id": str(random.randint(10**20, 10**21 - 1)),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": f"http://{host}:{port}/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{email}",
        "universe_domain": "googleapis.com",
    }
    Path(path).write_text(json.dumps(sa, indent=2) + "\n")
    os.chmod(path, 0o600)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--profile", default="unlimited")
    ap.add_argument(
        "--profiles",
        default=None,
        help="profiles JSON (default: profiles.json, else profiles.default.json)",
    )
    ap.add_argument(
        "--latency-scale",
        type=float,
        default=1.0,
        help="multiplies all latencies; 0 disables sleeping",
    )
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument(
        "--write-sa", metavar="PATH", help="write a fake service-account JSON and exit"
    )
    ap.add_argument(
        "--sa-host",
        default="127.0.0.1",
        help="host to put in the SA token_uri (e.g. host.docker.internal)",
    )
    ap.add_argument("--log-level", default="warning")
    args = ap.parse_args(argv)

    if args.write_sa:
        write_service_account(args.write_sa, args.port, args.sa_host)
        print(
            f"wrote {args.write_sa} (token_uri=http://{args.sa_host}:{args.port}/token)"
        )
        return

    profiles, src = load_profiles(args.profiles)
    if args.profile not in profiles:
        raise SystemExit(
            f"unknown profile {args.profile!r}; have {sorted(profiles)} (from {src})"
        )
    state = State(profiles[args.profile], args.latency_scale, args.seed)
    vectors = VectorCache(args.seed)
    for d in (3072, 1536, 768):  # warm the common dimensions
        vectors.get(d, 0)
    app = build_app(profiles, src, state, vectors)

    import importlib.util

    import uvicorn

    loop = "uvloop" if importlib.util.find_spec("uvloop") else "asyncio"
    http = "httptools" if importlib.util.find_spec("httptools") else "h11"
    print(
        f"mock-vertex on http://{args.host}:{args.port}/ profile={args.profile} "
        f"latency_scale={args.latency_scale} profiles={src} loop={loop} http={http}",
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(
        fast_path(app),
        host=args.host,
        port=args.port,
        workers=1,
        loop=loop,
        http=http,
        log_level=args.log_level,
        access_log=False,
        backlog=8192,
        limit_concurrency=None,
        timeout_keep_alive=120,
    )


if __name__ == "__main__":
    main()
