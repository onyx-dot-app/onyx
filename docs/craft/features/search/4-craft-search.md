# Part 4: Craft Integration — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 4)

## Objective

Wire onyx-cli into the Craft sandbox as the primary search tool, replacing the legacy `files/` corpus sync. Mint session-scoped PATs, bundle the CLI binary, create a `company-search` skill with the user's available sources, and tear down the file-sync infrastructure.

**Part 1 is complete.** The CLI binary accepts `ONYX_SERVER_URL` + `ONYX_PAT` env vars, has `search` and `validate-config` commands, and produces agent-optimized output without a TTY. **Parts 2–3 are assumed complete.** `POST /api/search` exists and returns ranked, permissioned results.

---

## End State

After this work, the sandbox has one path to company knowledge: `onyx-cli search`.

### What the agent sees

| Resource | Before | After |
|----------|--------|-------|
| Company knowledge | `find`/`grep` over JSON files in `files/` | `onyx-cli search "<query>"` |
| Available sources | Scanned from `files/` directory at setup | Listed in `company-search` SKILL.md, queried from user's connectors |
| Auth | None (files are pre-synced) | Session-scoped PAT via `ONYX_PAT` env var |
| AGENTS.md guidance | "Start at `files/`, use `find`/`grep`" | "Use the `company-search` skill" |

### What the sandbox contains

| Component | Before | After |
|-----------|--------|-------|
| `/workspace/files/` | S3-synced corpus dump | Gone |
| S3 sidecar container | Runs `s5cmd sync` at pod start | Gone |
| `onyx-cli` binary | Not present | `/usr/local/bin/onyx-cli` |
| `company-search` skill | Does not exist | `.opencode/skills/company-search/SKILL.md` with user's sources |
| `ONYX_PAT` env var | Not set | Session-scoped PAT, 7-day expiry |
| `ONYX_SERVER_URL` env var | Not set | Internal Kube service address |

### Session auth lifecycle

```
Session created / resumed
  └─ delete old PAT if one exists (handles resume after sleep)
  └─ mint fresh PAT (name: craft-session-{session_id}, expires: 7 days)
  └─ inject ONYX_PAT into sandbox environment
  └─ validate: onyx-cli validate-config
  └─ agent runs, calls onyx-cli search as needed
Session ended
  └─ delete PAT row (immediate, no soft-revoke)
  └─ if cleanup fails: PAT self-expires in ≤7 days
```

---

## Current State

- **One pod per user**, shared across sessions. Per-session workspaces at `/workspace/sessions/{session_id}/`.
- **File sync**: S3 sidecar syncs documents to `/workspace/files/`. Sessions symlink `files/` → `/workspace/files/`. `generate_agents_md.py` scans `files/` to populate `{{KNOWLEDGE_SOURCES_SECTION}}` in AGENTS.md.
- **Skills**: Baked into image at `/workspace/skills/`, symlinked into sessions.
- **No sandbox auth**: `BuildSession` has no token. The sandbox cannot call the Onyx API.
- **AGENTS.md**: References `files/`, JSON documents, `find`/`grep`.
- **OpenCode config**: Whitelists `/workspace/files` as an external directory.

### Open question — User Library

`PersistentDocumentWriter` has a live consumer in `user_library.py` that writes raw files (spreadsheets, PDFs) to persistent storage, synced into the sandbox at `files/user_library/`. These are files the agent opens directly — search results alone don't replace them. This dependency must be resolved before `PersistentDocumentWriter` can be fully deleted. The plan below flags where this blocks but does not pick a resolution.

---

## Implementation

### A. Session auth

**1. Mint PAT at workspace setup** (`server/features/build/session/manager.py`)

PAT minting happens in `setup_session_workspace()`, not `create_session__no_commit()`. This way the same code path handles both initial creation and session resume (after a sleeping sandbox is re-provisioned). On resume, the old pod is dead and the raw token is gone — we must issue a fresh one.

```python
# Delete any existing PAT for this session (idempotent — no-op if expired/missing)
pat_name = f"craft-session-{session.id}"
for pat in list_user_pats(db_session, session.user_id):
    if pat.name == pat_name:
        db_session.delete(pat)
        db_session.flush()

# Mint fresh PAT
pat_record, raw_token = create_pat(
    db_session=db_session,
    user_id=user.id,
    name=pat_name,
    expiration_days=7,
)
```

Pass `raw_token` to `setup_session_workspace()` as a new `api_key` parameter.

PAT names are not unique — minting a new one with the same name is fine. `list_user_pats` filters out expired rows, so the delete step only finds active PATs. 7-day expiry so long-running sessions don't break; delete-on-cleanup is the primary mechanism.

**2. Delete PAT at session cleanup** (`server/features/build/session/manager.py`)

In every teardown path (`cleanup_session_workspace()`, `delete_build_session__no_commit()`), **delete** the session PAT row — don't soft-revoke it. Session PATs have no audit value and would otherwise accumulate as dead rows (a daily Craft user generates ~1000+ revoked PAT rows per year).

```python
pat_name = f"craft-session-{session.id}"
for pat in list_user_pats(db_session, session.user_id):
    if pat.name == pat_name:
        db_session.delete(pat)
        db_session.flush()
        break
```

If cleanup fails, the 7-day expiry ensures the token stops working. The expired row is orphaned but it's one row, not an accumulating problem — the next session resume will delete it via the revoke-before-mint in step 1.

**3. Hide session PATs from user's PAT list** (`server/pat/api.py`)

Filter out PATs whose name starts with `craft-session-` from `GET /user/pats`:

```python
pats = [
    pat for pat in list_user_pats(db_session, user.id)
    if not pat.name.startswith("craft-session-")
]
```

Session PATs are infrastructure — users shouldn't have to see or manage them. No new fields or migration needed; the name prefix is the discriminator.

**4. Inject env vars into sandbox** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `setup_session_workspace()`, make `ONYX_PAT` and `ONYX_SERVER_URL` available to agent-launched processes. The mechanism depends on how OpenCode propagates environment to child processes — either via an env file sourced by the shell, exports in the session setup script, or a shell profile.

`ONYX_SERVER_URL` comes from a new config value:

```python
# server/features/build/configs.py
SANDBOX_ONYX_SERVER_URL = os.environ.get(
    "SANDBOX_ONYX_SERVER_URL",
    "http://api-server.onyx.svc.cluster.local:8080/api",
)
```

For local dev (`SandboxBackend.LOCAL`): defaults to `http://localhost:8080/api`.

**5. Validate at session start** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

After injecting env vars, before the agent starts:

```bash
ONYX_PAT="..." ONYX_SERVER_URL="..." onyx-cli validate-config
```

Non-zero exit → abort session setup with `OnyxError`. Better to fail immediately than let the agent discover mid-task that search is broken.

### B. Sandbox image

**6. Add onyx-cli to Dockerfile** (`sandbox/kubernetes/docker/Dockerfile`)

```dockerfile
COPY --chown=sandbox:sandbox onyx-cli /usr/local/bin/onyx-cli
RUN chmod +x /usr/local/bin/onyx-cli
```

The CI pipeline that builds the sandbox image must produce the CLI binary. Single static Go binary, no runtime dependencies.

**7. Add company-search skill** (`sandbox/kubernetes/docker/skills/company-search/`)

One file — `SKILL.md.template`:

```markdown
---
name: company-search
description: Search company knowledge using onyx-cli. Returns permissioned, citation-rich results from connected sources.
---

# company-search

Search the company's knowledge base — restricted to what the current user has
permission to see.

## Sources Available in This Session

{{AVAILABLE_SOURCES_SECTION}}

If a source you'd expect isn't listed, it isn't connected for this user — do not
assume it exists.

## Usage

    onyx-cli search "<query>"

| Flag | Description | Example |
|------|-------------|---------|
| `--source` | Filter by source type (comma-separated) | `--source slack,google_drive` |
| `--days` | Only return results from the last N days | `--days 30` |
| `--limit` | Maximum number of results | `--limit 5` |

## Output

Stdout is JSON with a top-level `results` array. Each result has a `document`
field (the citation ID), plus `title`, `content`, `source_type`, and other
metadata. Cite results by their `document` number when referencing them in your
response.
```

No `run.sh`. The agent calls `onyx-cli search` directly.

**8. Remove `/workspace/files/` from Dockerfile**

Delete `mkdir -p /workspace/files`. Remove the `COPY` of `generate_agents_md.py`.

### C. Session setup

**9. Render company-search SKILL.md** (`sandbox/util/agent_instructions.py`)

New function `build_available_sources_section(user, db_session)`:

1. Call `get_connector_credential_pairs_for_user(db_session, user, get_editable=False)`.
2. Group by source type.
3. For each source, render `- \`{source_name}\` — {description}`.

Descriptions come from a `SOURCE_DESCRIPTIONS` dict keyed by `DocumentSource` value, with a fallback to the source name. For Slack, Linear, and GitHub, append sub-scope examples (channel names, team names, repo names) extracted from `connector_specific_config`, capped at 5 entries.

Example rendered output:

```
- `google_drive` — Documents, spreadsheets, and presentations
- `slack` — Team messages and channel discussions (#eng, #sales, #product, ...)
- `linear` — Engineering and product tickets
```

If the user has no connectors: `"No connected sources available for this user."`

In `SessionManager`, render the template by replacing `{{AVAILABLE_SOURCES_SECTION}}` and pass the result to `setup_session_workspace()`.

**10. Copy skills instead of symlinking** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

Currently: `ln -sf /workspace/skills {session_path}/.opencode/skills`

Change to:

```bash
mkdir -p {session_path}/.opencode/skills
cp -r /workspace/skills/* {session_path}/.opencode/skills/
echo "{base64_rendered_skill_md}" | base64 -d \
    > {session_path}/.opencode/skills/company-search/SKILL.md
```

Copy instead of symlink because company-search needs per-session rendering. The skills directory is small — two skill bundles.

**11. Rewrite AGENTS.template.md** (`server/features/build/AGENTS.template.md`)

Delete the "Knowledge Sources" section, `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder, the JSON document format note, and all `files/` references. Replace "Step 1: Information Retrieval":

```markdown
### Step 1: Information Retrieval

1. **Search** company knowledge using the `company-search` skill. Run
   `onyx-cli search "<query>"` and read the returned JSON; each result has a
   `document` field (the citation ID) — cite results by that number when you
   reference them.
2. Read the `company-search` SKILL.md for available sources and flags.
3. **Iterate** — run additional searches to refine. Use `--source` to narrow by
   connector and `--days` for recent content.
4. **Summarize** key findings before proceeding to output generation.
```

Keep everything else (Configuration, Environment, Skills, Behavior Guidelines, Outputs).

### D. File sync removal

Everything below removes dead code. The replacement is wired up in A–C.

**12. Remove S3 sidecar** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `_create_sandbox_pod()`: remove the file-sync sidecar container, its EmptyDir volume, AWS credential injection, and references to `SANDBOX_FILE_SYNC_SERVICE_ACCOUNT` and `SANDBOX_S3_BUCKET`.

**13. Remove files/ symlink from session setup** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `setup_session_workspace()`: delete the `files/` symlink creation (both real-data and demo-data paths) and the filtered-symlink script for excluded paths.

**14. Remove knowledge sources rendering** (`sandbox/util/agent_instructions.py`)

Delete `CONNECTOR_INFO`, `_normalize_connector_name()`, `_scan_directory_to_depth()`, `build_knowledge_sources_section()`, the `{{KNOWLEDGE_SOURCES_SECTION}}` replacement in `generate_agent_instructions()`, and the `files_path` parameter. Update all callers.

**15. Delete `generate_agents_md.py`** (`sandbox/kubernetes/docker/generate_agents_md.py`)

This script existed solely to populate `{{KNOWLEDGE_SOURCES_SECTION}}` by scanning `files/` inside the container. With the placeholder gone, the script is dead.

**16. Remove `/workspace/files` allowlist** (`sandbox/util/opencode_config.py`)

Remove the `/workspace/files` and `/workspace/files/**` allow rules from `external_directory`. Keep `/workspace/demo_data` rules if demo data survives (see §17).

**17. Remove docfetching writer path** (`background/indexing/run_docfetching.py`)

Remove the `get_persistent_document_writer()` call and the code path that writes indexed documents to persistent storage. This is the connector-document sync path — dead with `files/` gone.

**Cannot fully delete `persistent_document_writer.py`** — `user_library.py` still uses it for raw file writes. See "Open question — User Library" above.

**18. Demo data**

`demo_data/` is baked into the image (not S3-synced). Removing the `files/` symlink means the agent can't read it via file operations. If demo data is indexed in Vespa, it works via `onyx-cli search` automatically. If it's file-only, index it. Do not preserve the `files/` symlink for demo mode — that keeps dead infrastructure alive for one edge case.

### E. Local development

Apply the same changes to the local sandbox manager (`sandbox/manager/directory_manager.py`): mint PAT, inject env vars, copy + render skills, remove `files/` symlink. `ONYX_SERVER_URL` defaults to `http://localhost:8080/api`. The CLI binary must be on the developer's `$PATH`.

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `sandbox/kubernetes/docker/skills/company-search/SKILL.md.template` | Skill template with `{{AVAILABLE_SOURCES_SECTION}}` placeholder |

### Modified Files

| File | Change |
|------|--------|
| `server/features/build/session/manager.py` | Mint PAT at workspace setup, revoke at cleanup, pass `api_key` to workspace setup |
| `server/pat/api.py` | Filter `craft-session-*` PATs from `GET /user/pats` |
| `server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` | Remove sidecar, remove files/ symlink, inject env vars, copy skills, run validation |
| `server/features/build/sandbox/kubernetes/docker/Dockerfile` | Add onyx-cli binary, remove files/ dir, remove generate_agents_md.py copy |
| `server/features/build/sandbox/util/agent_instructions.py` | Add `build_available_sources_section()`, delete `CONNECTOR_INFO` and `build_knowledge_sources_section()` |
| `server/features/build/sandbox/util/opencode_config.py` | Remove `/workspace/files` allowlist |
| `server/features/build/AGENTS.template.md` | Rewrite: remove files/ references, point at company-search |
| `server/features/build/configs.py` | Add `SANDBOX_ONYX_SERVER_URL` |
| `server/features/build/sandbox/manager/directory_manager.py` | Local backend: same changes as K8s |
| `background/indexing/run_docfetching.py` | Remove persistent document writer call |

### Deleted Files

| File | Reason |
|------|--------|
| `sandbox/kubernetes/docker/generate_agents_md.py` | Only populated `{{KNOWLEDGE_SOURCES_SECTION}}` from files/ |
| `tests/external_dependency_unit/craft/test_persistent_document_writer.py` | Tests deleted code path |

---

## Execution Order

```
Step 1: Session auth (§A)           — PATs minted but sandbox doesn't use them yet
    │
Step 2: Sandbox image (§B)          — CLI available, skill baked in, not yet wired
    │
Step 3: Session setup (§C)          — agent sees search tool alongside files/
    │
Step 4: File sync removal (§D)      — the cutover, ship after verifying search works
```

Steps 1–3 can land incrementally. Step 4 is the breaking change — ship after confirming search works end-to-end.

---

## Tests

### External Dependency Unit Tests

**File:** `tests/external_dependency_unit/craft/test_company_search_skill.py`

1. **Source list rendering.** Create test CC pairs, call `build_available_sources_section()`, assert correct sources and descriptions.
2. **Empty sources.** User with no connectors → `"No connected sources available for this user."`.
3. **Sub-scope examples.** Slack connector with channel config → channels appear in output.

### Integration Tests

**File:** `tests/integration/tests/craft/test_craft_search_e2e.py`

1. **Full round-trip.** Create session → verify PAT minted → `onyx-cli search` returns results inside sandbox → end session → verify PAT revoked.

### Smoke Tests

1. Run a Craft session, watch the agent use `onyx-cli search`, confirm it cites real results.
2. Same query in Onyx chat — top results should overlap.
3. `find files/` returns nothing.
4. Session with no sources — SKILL.md says so, agent doesn't hallucinate.
