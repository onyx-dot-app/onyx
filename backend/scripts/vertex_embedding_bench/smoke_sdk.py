"""End-to-end check: real google-genai SDK (and Onyx's `_embed_vertex`) against mock_vertex.

Start the mock first:
    python mock_vertex.py --write-sa .cache/mock-sa.json --port 8799
    python mock_vertex.py --port 8799 --profile unlimited --latency-scale 0 &
Then:
    python smoke_sdk.py --sa .cache/mock-sa.json
    # include Onyx's own CloudEmbedding path:
    PYTHONPATH=<onyx backend> python smoke_sdk.py --sa .cache/mock-sa.json --onyx

The script switches the mock's profile (to `tiny_rpm`, then back) and resets its counters.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


async def sdk_checks(
    base: str, sa_path: str, rpm_profile: str, restore_profile: str
) -> BaseException:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = genai.Client(
        vertexai=True, project="mock-project", location="us-central1", credentials=creds
    )
    ctl = httpx.AsyncClient(base_url=base, timeout=30)
    await ctl.post("/reset")

    print("gemini-embedding-2 (embedContent, 1 input)")
    r = await client.aio.models.embed_content(
        model="gemini-embedding-2",
        contents=[
            types.Content(
                parts=[types.Part(text="task: search result | query: hello world")]
            )
        ],
        config=types.EmbedContentConfig(output_dimensionality=3072, auto_truncate=True),
    )
    assert r.embeddings and len(r.embeddings) == 1
    vals = r.embeddings[0].values or []
    assert len(vals) == 3072, len(vals)
    _ok(f"len={len(vals)} first={vals[:3]} stats={r.embeddings[0].statistics}")

    r = await client.aio.models.embed_content(
        model="gemini-embedding-2",
        contents=["short"],
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    assert r.embeddings
    assert len(r.embeddings[0].values or []) == 768
    _ok("output_dimensionality=768 honoured")

    try:
        two: list[types.ContentUnion] = [
            types.Content(parts=[types.Part(text=t)]) for t in ("a", "b")
        ]
        await client.aio.models.embed_content(model="gemini-embedding-2", contents=two)
        raise AssertionError("expected the SDK to refuse 2 contents")
    except ValueError as e:
        _ok(f"SDK refuses >1 content client-side: {e}")
    # Bypass the SDK to prove the server enforces it too.
    token = creds.token
    raw = await ctl.post(
        "/v1beta1/projects/mock-project/locations/us-central1/publishers/google/models/gemini-embedding-2:predict",
        json={"instances": [{"content": "a"}, {"content": "b"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert (
        raw.status_code == 400 and raw.json()["error"]["status"] == "INVALID_ARGUMENT"
    ), raw.text
    _ok(
        f"server rejects 2 instances for gemini-embedding-2: {raw.status_code} {raw.json()['error']['status']}"
    )

    print("gemini-embedding-001 (predict, several inputs)")
    texts: list[types.ContentUnion] = ["alpha", "beta gamma", "delta epsilon zeta"]
    r = await client.aio.models.embed_content(
        model="gemini-embedding-001",
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=1536,
            auto_truncate=True,
        ),
    )
    assert r.embeddings and len(r.embeddings) == 3
    assert all(len(e.values or []) == 1536 for e in r.embeddings)
    _ok(
        f"{len(r.embeddings)} embeddings x {len(r.embeddings[0].values or [])} dims, metadata={r.metadata}"
    )

    r = await client.aio.models.embed_content(
        model="text-embedding-005", contents=texts
    )
    assert r.embeddings
    assert len(r.embeddings[0].values or []) == 768
    _ok("text-embedding-005 default 768 dims")

    print(f"429 on profile {rpm_profile!r}")
    await ctl.post(f"/profile/{rpm_profile}")
    await ctl.post("/reset")
    got_429 = None
    for i in range(50):
        try:
            await client.aio.models.embed_content(
                model="gemini-embedding-2", contents=[f"x{i}"]
            )
        except genai_errors.ClientError as e:
            got_429 = e
            break
    assert got_429 is not None, "no 429 raised"
    assert got_429.code == 429 and got_429.status == "RESOURCE_EXHAUSTED"
    assert isinstance(got_429, genai_errors.APIError)
    _ok(
        f"after {i} ok calls: {type(got_429).__module__}.{type(got_429).__name__} code={got_429.code} "
        f"status={got_429.status} message={(got_429.message or '')[:60]!r}..."
    )

    stats = (await ctl.get("/stats")).json()
    _ok(
        f"stats: ok={stats['ok']} throttled_429={stats['throttled_429']} token_requests={stats['token_requests']}"
    )
    await ctl.post(f"/profile/{restore_profile}")
    await ctl.post("/reset")
    await client.aio.aclose()
    await ctl.aclose()
    return got_429


async def onyx_check(sa_json: str, sdk_429: BaseException) -> None:
    """Runs Onyx's own CloudEmbedding._embed_vertex path (no DB needed)."""
    from onyx.natural_language_processing.embedding_auth import build_embedding_auth
    from onyx.natural_language_processing.search_nlp_models import (
        CloudEmbedding,
        is_rate_limit_error,
    )

    assert is_rate_limit_error(sdk_429)
    _ok("Onyx is_rate_limit_error() recognises the mock's 429")
    from shared_configs.enums import EmbeddingProvider, EmbedTextType

    for model, dim in (("gemini-embedding-2", 3072), ("gemini-embedding-001", 768)):
        auth = build_embedding_auth(
            EmbeddingProvider.GOOGLE,
            sa_json,
            {
                "auth_method": "service_account_json",
                "project_id": None,
                "location": "us-central1",
            },
        )
        ce = CloudEmbedding(
            api_key=sa_json, provider=EmbeddingProvider.GOOGLE, auth=auth
        )
        embs = await ce.embed(
            texts=["Onyx passage one.", "Onyx passage two.", "Onyx passage three."],
            text_type=EmbedTextType.PASSAGE,
            model_name=model,
            reduced_dimension=dim,
        )
        assert len(embs) == 3 and all(len(e) == dim for e in embs), [
            len(e) for e in embs
        ]
        _ok(f"Onyx CloudEmbedding({model}) -> {len(embs)} x {dim}")
        await ce.aclose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base-url",
        default=os.environ.get("MOCK_VERTEX_URL", "http://127.0.0.1:8799/"),
    )
    ap.add_argument(
        "--sa", required=True, help="fake SA JSON from `mock_vertex.py --write-sa`"
    )
    ap.add_argument("--rpm-profile", default="tiny_rpm")
    ap.add_argument("--restore-profile", default="unlimited")
    ap.add_argument(
        "--onyx",
        action="store_true",
        help="also run Onyx's CloudEmbedding (needs PYTHONPATH=<onyx>/backend)",
    )
    args = ap.parse_args()

    base = args.base_url.rstrip("/") + "/"
    os.environ["GOOGLE_VERTEX_BASE_URL"] = base
    sa = json.loads(Path(args.sa).read_text())
    if not sa["token_uri"].startswith(base.rstrip("/")):
        print(
            f"WARNING: SA token_uri {sa['token_uri']} is not on {base}", file=sys.stderr
        )

    print(f"GOOGLE_VERTEX_BASE_URL={base}")
    sdk_429 = asyncio.run(
        sdk_checks(base, args.sa, args.rpm_profile, args.restore_profile)
    )
    if args.onyx:
        print("Onyx CloudEmbedding._embed_vertex")
        asyncio.run(onyx_check(Path(args.sa).read_text(), sdk_429))
    print("ALL OK")


if __name__ == "__main__":
    main()
