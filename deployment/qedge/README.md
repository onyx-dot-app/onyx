# QEdge Beta RAG source archive

This branch preserves the final Beta patch from 2026-11-13.
The application files match the server source byte for byte.
The source baseline is Onyx v5.1.2, commit `6b627422c711802fee78b89dda3e25ca0f48ec7e`.
This branch does not rebase onto the older fork main.

## Trace the source

- `patches/onyx-v5.1.2-rag-summary.patch` is the exact downloaded server patch.
- `source-provenance.json` records its SHA-256 and all 17 source file hashes.
- The same 17 files are applied as normal source changes in this branch.
- Runtime secrets, database backups, and host-specific Compose overrides are excluded.

Patch SHA-256:

```text
ae5c92301897de4f78af87642d5c81b31554ccb1eb773d5f21c034933b2beaba
```

To apply the original patch separately, use a clean checkout at the baseline commit.
Do not apply it again on this branch.

```sh
git checkout 6b627422c711802fee78b89dda3e25ca0f48ec7e
git apply --check /path/to/onyx-v5.1.2-rag-summary.patch
git apply /path/to/onyx-v5.1.2-rag-summary.patch
```

## Build the backend overlay

Run from the repository root:

```sh
docker build -f deployment/qedge/Dockerfile.rag-stable -t onyx-backend:v5.1.2-rag-stable .
```

The Dockerfile copies all nine changed backend modules onto the v5.1.2 backend image.
It is a build recipe for the archived source. This archive task did not rebuild or redeploy the live service.
Set `ONYX_BASE_IMAGE` with a build argument if an approved image digest is available.

Both ordinary summaries and deeper analysis use the configured Flash model.
Read `documentation/admins/managing_features/rag_and_search.mdx` for the custom route.
The two environment templates document its settings.
Enabling the route requires explicit Agent IDs and an existing model provider.
No provider credentials are stored in this branch.
Use the HTTP-only Nginx template only behind the intended TLS terminator and network access controls.

## Validation

During archive preparation:

- The patch applied cleanly to the exact baseline.
- All 17 restored file Git blobs matched the patch postimages.
- All 17 restored SHA-256 hashes matched the current server source.
- All changed Python files passed local syntax parsing.
- The patch passed a credential-literal review.

Earlier deployment validation recorded 25 passing unit tests, 19 question cases, and five integration checks.
These are historical results from the deployment task, not fresh archive test results.
A fresh test attempt lost its SSH connection before completion; no fresh pass is claimed.
The original patch retains its exact formatting, including a trailing blank line in the HTTP-only template.

With the repository dependencies installed, run the included regression suite from the root:

```sh
PYTHONPATH=backend uv run python -m unittest test_knowledge_rag
```
