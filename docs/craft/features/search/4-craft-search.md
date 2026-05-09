# Part 4: Craft Integration — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 4)

## Objective

Wire onyx-cli into the Craft sandbox as the primary search tool, replacing the legacy `files/` corpus sync. Mint session-scoped PATs, bundle the CLI, create a `company-search` skill with the user's available sources, rewrite AGENTS.md, and tear down the file-sync infrastructure.

**Assumes Parts 1–3 are complete.** The CLI binary accepts `ONYX_SERVER_URL` + `ONYX_API_KEY` env vars, has `search` and `validate-config` commands, and produces agent-optimized output without a TTY. `POST /api/search` exists and returns ranked, permissioned results.

---

## Issues to Address

1. **No sandbox-to-backend auth.** The sandbox has no mechanism to call the Onyx API as the session's user. The CLI needs credentials.
2. **No search tool in the sandbox.** The agent's only path to company knowledge is `find`/`grep` over JSON files in `files/`. The search tool replaces this.
3. **File sync is the wrong primitive.** S3 sidecar syncs a corpus dump per pod. It's slow, unpermissioned, stale after session start, and blows context windows. Deleting it is the goal.
4. **AGENTS.md teaches the wrong workflow.** It tells the agent to scan `files/` with `find`/`grep`. Needs rewriting.

---

## Important Notes

**What exists today:**
- One sandbox pod per user, shared across sessions. Per-session workspaces at `/workspace/sessions/{session_id}/`.
- S3 sidecar (`peakcom/s5cmd`) syncs connector documents to `/workspace/files/`. Each session symlinks `{session_path}/files/` → `/workspace/files/`.
- Skills baked into Docker image at `/workspace/skills/`, symlinked into sessions.
- PATs: `PersonalAccessToken` model, created via `create_pat()`, hashed with SHA256, revoked by setting `expires_at=NOW()`.
- `AGENTS.template.md` references `files/`, JSON documents, `find`/`grep`. `agent_instructions.py` has `build_knowledge_sources_section()` and `CONNECTOR_INFO` dict for scanning the `files/` directory.
- `opencode_config.py` whitelists `/workspace/files` as an external directory.

**Open question — User Library:** `PersistentDocumentWriter` has a live consumer in `user_library.py` that writes raw files (spreadsheets, PDFs) to persistent storage, synced into the sandbox at `files/user_library/`. These are files the agent opens directly — they can't be replaced by search results alone. This dependency must be resolved before `PersistentDocumentWriter` can be deleted. Options: (a) write user library files to a separate path that survives the `files/` removal, (b) route user library through `attachments/`, or (c) keep a scoped `user_library/` path. The plan below flags where this blocks deletion but does not pick an option — it needs a decision.

---

## Implementation

### 1. Session-Scoped PAT Lifecycle

At session creation, mint a PAT for the session's user. At cleanup, revoke it. The 24h expiry is the safety net for failed cleanups.

**Minting** — in `SessionManager.create_session__no_commit()`, after creating the `BuildSession` record:

```python
pat_record, raw_token = create_pat(
    db_session=db_session,
    user_id=user.id,
    name=f"craft-session-{session.id}",
    expiration_days=1,
)
```

Pass `raw_token` to `setup_session_workspace()` for injection into the sandbox environment.

The naming convention `craft-session-{session_id}` is the join key — no new columns or migrations needed. The PAT name identifies which session owns it, and `list_user_pats()` already returns names to the UI.

**Revocation** — in every session teardown path (`cleanup_session_workspace()`, `delete_build_session__no_commit()`):

```python
# Find and revoke the session's PAT
pats = list_user_pats(db_session, session.user_id)
for pat in pats:
    if pat.name == f"craft-session-{session.id}":
        revoke_pat(db_session, pat.id, session.user_id)
        break
```

If cleanup fails (crash, orphaned pod), the PAT expires in ≤24h. No sweep task needed — the expiry is the sweep.

### 2. CLI Binary and Environment

**Dockerfile** — add onyx-cli to the sandbox image:

```dockerfile
COPY --chown=sandbox:sandbox onyx-cli /usr/local/bin/onyx-cli
RUN chmod +x /usr/local/bin/onyx-cli
```

The CI pipeline that builds the sandbox image must produce the CLI binary as a build artifact. Single static Go binary, no runtime dependencies.

**Environment injection** — in `setup_session_workspace()`, write the CLI env vars so they're available to agent-launched processes:

```bash
export ONYX_API_KEY="{raw_pat_token}"
export ONYX_SERVER_URL="{internal_backend_url}"
```

The mechanism (env file sourced by the shell, export in the session setup script, or written into a profile) depends on how OpenCode launches subprocesses. The requirement is: when the agent runs `onyx-cli search`, those vars are set.

**`ONYX_SERVER_URL`** — new config in `configs.py`:

```python
SANDBOX_ONYX_SERVER_URL = os.environ.get(
    "SANDBOX_ONYX_SERVER_URL",
    "http://api-server.onyx.svc.cluster.local:8080",
)
```

Internal Kube service address. For local dev: `http://localhost:8080`.

### 3. Company-Search Skill

**Skill bundle** — new directory at `sandbox/kubernetes/docker/skills/company-search/` containing one file:

`SKILL.md.template`:
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

Stdout is markdown with numbered citations like `[1]`, `[2]`. Cite results by
their citation number when referencing them in your response.
```

No `run.sh`. The agent calls `onyx-cli search` directly.

**Source list rendering** — new function in `agent_instructions.py`:

```python
def build_available_sources_section(user: User, db_session: Session) -> str:
```

Queries `get_connector_credential_pairs_for_user(db_session, user, get_editable=False)`, groups by source type, and formats:

```
- `google_drive` — Documents, spreadsheets, and presentations
- `slack` — Team messages and channel discussions (#eng, #sales, #product, ...)
- `linear` — Engineering and product tickets
```

Each source gets a one-line description from a `SOURCE_DESCRIPTIONS` dict (keyed by `DocumentSource` value, fallback to the source name). For Slack, Linear, and GitHub, include a few sub-scope examples (channel names, team names, repo names) extracted from `connector_specific_config`. If the user has no connectors, output `"No connected sources available for this user."`.

**Materialization** — in `setup_session_workspace()`:

Currently skills are symlinked: `ln -sf /workspace/skills {session_path}/.opencode/skills`. Since company-search needs per-session rendering, switch to copying:

```bash
mkdir -p {session_path}/.opencode/skills
cp -r /workspace/skills/* {session_path}/.opencode/skills/
```

Then overwrite the template with the rendered version:

```bash
echo "{base64_rendered_skill_md}" | base64 -d > {session_path}/.opencode/skills/company-search/SKILL.md
```

The rendering happens server-side in `SessionManager` before calling `setup_session_workspace()`. The rendered content is passed as a parameter and written via kubectl exec.

### 4. AGENTS.template.md Rewrite

Delete the "Knowledge Sources" section, `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder, the JSON document format note, and the `files/` references. Replace "Step 1: Information Retrieval" with:

```markdown
### Step 1: Information Retrieval

1. **Search** company knowledge using the `company-search` skill. Run
   `onyx-cli search "<query>"` and read the returned markdown; cite results by
   their citation number when you reference them.
2. Read the `company-search` SKILL.md for available sources and flags.
3. **Iterate** — run additional searches to refine. Use `--source` to narrow by
   connector and `--days` for recent content.
4. **Summarize** key findings before proceeding to output generation.
```

Keep everything else (Configuration, Environment, Skills, Behavior Guidelines, Outputs).

### 5. Startup Validation

After injecting env vars and before the agent starts, run:

```bash
ONYX_API_KEY="..." ONYX_SERVER_URL="..." onyx-cli validate-config
```

If the exit code is non-zero (auth failure, backend unreachable), abort session setup and surface the error to the user. Better to fail immediately than let the agent discover mid-task that search is broken.

### 6. Decommission File Sync

Everything below removes dead code. The replacement (onyx-cli search) is wired up in §1–5.

**Remove from `_create_sandbox_pod()`:**
- The file-sync sidecar container (peakcom/s5cmd)
- The `files-volume` EmptyDir (verify sessions volume is separate)
- AWS credential injection for the sidecar (`_get_local_aws_credential_env_vars` if only used here)
- References to `SANDBOX_FILE_SYNC_SERVICE_ACCOUNT`, `SANDBOX_S3_BUCKET` (verify no other consumers)

**Remove from `setup_session_workspace()`:**
- The `files/` symlink creation (both real-data and demo-data paths)
- The filtered-symlink script for excluded paths
- The call to `generate_agents_md.py` (the `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder no longer exists)

**Remove from `agent_instructions.py`:**
- `CONNECTOR_INFO` dict
- `_normalize_connector_name()`, `_scan_directory_to_depth()`, `build_knowledge_sources_section()`
- The `{{KNOWLEDGE_SOURCES_SECTION}}` replacement in `generate_agent_instructions()`
- The `files_path` parameter from `generate_agent_instructions()` (update all callers)

**Remove from Dockerfile:**
- `mkdir -p /workspace/files`
- The `COPY` of `generate_agents_md.py`

**Delete files:**
- `sandbox/kubernetes/docker/generate_agents_md.py`
- `tests/external_dependency_unit/craft/test_persistent_document_writer.py` (tests deleted code)

**Remove from `opencode_config.py`:**
- `/workspace/files` and `/workspace/files/**` allowlist rules

**Remove from `session/manager.py`:**
- The `PERSISTENT_DOCUMENT_STORAGE_PATH` import and usage for constructing the knowledge files path

**Remove from `run_docfetching.py`:**
- The `get_persistent_document_writer()` call and the code path that writes indexed documents to persistent storage for sandbox consumption

**`PersistentDocumentWriter` — partial deletion only.** Cannot fully delete `persistent_document_writer.py` because `user_library.py` depends on it for writing raw files (spreadsheets, etc.) to persistent storage. The indexed-document writing path (used by `run_docfetching.py`) is dead and should be removed. The raw-file writing path (used by `user_library.py`) must be preserved or replaced. See "Open question — User Library" in Important Notes.

### 7. Demo Data

The `demo_data/` directory is baked into the Docker image and symlinked into sessions when `demo_data_enabled=True`. It does NOT go through S3 file sync — it's static.

Removing the `files/` symlink means the agent can no longer read demo data via file operations. If demo data is indexed in Vespa, it's searchable via `onyx-cli search` and works automatically. If it's file-only (never indexed), it breaks.

**Decision:** Verify whether demo data is indexed. If yes, no changes needed beyond removing the symlink. If no, index it — this makes the demo consistent with the real product experience. Do not preserve the `files/` symlink for demo mode only; that would leave dead infrastructure alive for one edge case.

### 8. Local Development

Apply the same changes to the local sandbox manager (`directory_manager.py`):
- Mint session PAT and write env vars to the session workspace
- Copy skills and render company-search SKILL.md
- Remove `files/` symlink creation
- `ONYX_SERVER_URL` defaults to `http://localhost:8080`
- The onyx-cli binary must be on the developer's `$PATH`

---

## Execution Order

1. **PAT lifecycle** (§1) — sessions get PATs. No runtime impact (sandbox doesn't use them yet).
2. **CLI + env injection** (§2) — CLI available in sandbox. Not yet used by the agent.
3. **Skill + AGENTS.md** (§3, §4) — agent learns about search. Both paths (search + files) available briefly.
4. **Validation** (§5) — verify search works before agent starts.
5. **Decommission file sync** (§6) — the breaking change. Ship after verifying search works end-to-end.
6. **Demo data** (§7) — handle based on indexing findings.

Steps 1–4 can land incrementally. Step 5 is the cutover.

---

## Tests

**External dependency unit test** — `tests/external_dependency_unit/craft/test_company_search_skill.py`:

- Create test connector-credential pairs, call `build_available_sources_section()`, verify output lists correct sources with descriptions.
- User with no connectors → "No connected sources available."
- Slack connector with channel config → channels appear in description.

**Integration test** — `tests/integration/tests/craft/test_craft_search_e2e.py`:

- Create session → verify PAT minted → `onyx-cli search` returns results inside sandbox → end session → verify PAT revoked.

**Manual smoke** (before merging):

1. Run a Craft session, watch the agent use `onyx-cli search`, confirm it cites real results.
2. Run the same query in Onyx chat — top results should overlap.
3. `find files/` returns nothing.
4. Start a session with no sources — SKILL.md says so, agent doesn't hallucinate.
