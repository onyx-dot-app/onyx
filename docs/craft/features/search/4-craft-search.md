# Part 4: Craft Integration — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 4)

## Objective

Wire onyx-cli into the Craft sandbox as the primary search tool, replacing the legacy `files/` corpus sync entirely. This part handles: session-scoped PAT lifecycle, CLI binary bundling, company-search skill creation, available-sources injection, AGENTS.md rewrite, file-sync decommissioning, and startup validation.

**Assumes all prior work is completed:** Part 1 (agent-first CLI), Part 2 (`POST /api/search` endpoint with full SearchTool pipeline), and Part 3 (CLI `search` command wrapping the API). The CLI binary exists, accepts `ONYX_SERVER_URL` + `ONYX_API_KEY` env vars, has a `search` command with `--source`, `--days`, `--limit`, `--json` flags, and a `validate-config` command with `--json` and feature detection.

---

## Requirements Summary

| ID | Requirement | Section |
|----|-------------|---------|
| R4.1 | Session-scoped PAT lifecycle | [§1 PAT Lifecycle](#1-session-scoped-pat-lifecycle) |
| R4.2 | CLI binary bundling in sandbox image | [§2 CLI Bundling](#2-cli-binary-bundling) |
| R4.3 | company-search skill creation | [§3 Skill Creation](#3-company-search-skill-creation) |
| R4.4 | Available sources injection into SKILL.md | [§4 Sources Injection](#4-available-sources-injection) |
| R4.5 | Decommission file sync | [§5 Decommission File Sync](#5-decommission-file-sync) |
| R4.6 | Validation at session start | [§6 Startup Validation](#6-validation-at-session-start) |
| R4.7 | Demo data path | [§7 Demo Data](#7-demo-data-path) |

---

## Important Notes

### Current architecture (what exists today)

- **One sandbox per user**, shared across sessions. Pod created by `KubernetesSandboxManager._create_sandbox_pod()`. Per-session workspaces live under `/workspace/sessions/{session_id}/`.
- **File sync**: S3 sidecar (`peakcom/s5cmd`) syncs connector documents to `/workspace/files/`. Each session symlinks `{session_path}/files/` → `/workspace/files/` (or `/workspace/demo_data/`). AGENTS.md's `{{KNOWLEDGE_SOURCES_SECTION}}` is populated by scanning `files/` on disk via `generate_agents_md.py`.
- **Skills**: Baked into the Docker image at `/workspace/skills/`. Symlinked into sessions: `ln -sf /workspace/skills {session_path}/.opencode/skills`. AGENTS.md lists them via `{{AVAILABLE_SKILLS_SECTION}}`.
- **PATs**: `PersonalAccessToken` model in `db/models.py:499`. Created via `create_pat()` in `db/pat.py`. Hashed with SHA256, validated via `fetch_user_for_pat()`. Format: `onyx_pat_{tenant}.{random}`. Revoked by setting `expires_at=NOW()` + `is_revoked=True`.
- **No existing sandbox auth token**. `BuildSession` has no `sandbox_token` column. The sandbox currently has no mechanism to call the Onyx API as the session's user.
- **Agent instructions**: `AGENTS.template.md` references `files/` directory, JSON document format, `find`/`grep` over knowledge sources. `agent_instructions.py` has `build_knowledge_sources_section()` and `CONNECTOR_INFO` dict.
- **OpenCode config**: `opencode_config.py` whitelists `/workspace/files` and `/workspace/demo_data` as external directories.

### Key files

| File | Current role | What changes |
|------|-------------|-------------|
| `db/models.py:5151` (BuildSession) | Session metadata | Add `sandbox_token` column |
| `db/pat.py` | PAT CRUD | Add session-scoped PAT creation + cleanup helpers |
| `server/features/build/session/manager.py` | Session lifecycle | Mint PAT at creation, revoke at cleanup, inject env vars |
| `server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` | Pod creation + workspace setup | Remove S3 sidecar, add CLI binary, inject `ONYX_API_KEY` + `ONYX_SERVER_URL`, replace `files/` symlink with CLI validation |
| `server/features/build/sandbox/kubernetes/docker/Dockerfile` | Sandbox image | Add onyx-cli binary, add company-search skill, remove `files/` directory |
| `server/features/build/sandbox/util/agent_instructions.py` | AGENTS.md generation | Delete `build_knowledge_sources_section`, `CONNECTOR_INFO`. Add `render_company_search_skill_md()`. |
| `server/features/build/sandbox/kubernetes/docker/generate_agents_md.py` | K8s-side AGENTS.md population | Delete (no longer needed — no `{{KNOWLEDGE_SOURCES_SECTION}}` to populate post-file-sync) |
| `server/features/build/AGENTS.template.md` | Agent instructions template | Rewrite: remove `files/` references, point at `company-search` skill |
| `server/features/build/sandbox/util/opencode_config.py` | OpenCode permission config | Remove `/workspace/files` allowlist rules |
| `server/features/build/indexing/persistent_document_writer.py` | Document sync to filesystem/S3 | Delete (no consumers after file sync removal) |
| `server/features/build/configs.py` | Build-mode config constants | Remove `PERSISTENT_DOCUMENT_STORAGE_PATH` if no other consumers |

### Constraints

- **onyx-cli binary must be baked into the Docker image**, not downloaded at runtime. Version pinned to the Onyx release.
- **The sandbox never receives long-lived credentials.** The session PAT is short-lived (24h expiry) and revoked on session end.
- **Backwards compatibility is not a goal.** Active sessions will break on deploy. This is explicitly accepted.
- **The company-search skill uses the CLI directly** — no shell script wrapper around `curl`. The CLI is the tool.
- **Internal Kube service URL** for `ONYX_SERVER_URL` — the sandbox reaches the backend via `http://{service}.{namespace}.svc.cluster.local:{port}`, not the public nginx URL.

---

## Proposed Implementation

### 1. Session-Scoped PAT Lifecycle

#### 1a. Database: Add `sandbox_token` column to `BuildSession`

**File:** `backend/onyx/db/models.py`

Add a column to `BuildSession`:

```python
sandbox_token_hash: Mapped[str | None] = mapped_column(
    String(64), nullable=True, unique=True, index=True
)
```

We store the **hash** (SHA256, same as `PersonalAccessToken.hashed_token`), not the raw token. The raw token exists only:
1. In the minting response (returned from `create_pat()`)
2. Injected as `ONYX_API_KEY` env var inside the sandbox

This column is a reference to the session's PAT — used for cleanup (revoke the PAT when the session ends) and audit (which session owns which PAT). We use the hash because it's the PAT's stable identifier in the `personal_access_token` table.

**Why not a foreign key to `personal_access_token`?** PAT revocation sets `expires_at=NOW()` but doesn't delete the row. A FK would work but adds coupling. The hash is sufficient for lookup and is already the unique key on `personal_access_token.hashed_token`.

#### 1b. Migration

**File:** `backend/alembic/versions/<new>_add_sandbox_token_to_build_session.py`

```python
def upgrade():
    op.add_column(
        "build_session",
        sa.Column("sandbox_token_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_build_session_sandbox_token_hash",
        "build_session",
        ["sandbox_token_hash"],
        unique=True,
    )

def downgrade():
    op.drop_index("ix_build_session_sandbox_token_hash")
    op.drop_column("build_session", "sandbox_token_hash")
```

Nullable because existing sessions don't have tokens. New sessions always get one. No backfill needed — existing sessions will never have a working sandbox token, and they'll get new tokens on next session creation anyway.

#### 1c. PAT Minting at Session Creation

**File:** `backend/onyx/server/features/build/session/manager.py` — `create_session__no_commit()`

After creating the `BuildSession` record and before `setup_session_workspace()`:

1. Call `create_pat(db_session, user_id=user.id, name=f"craft-session-{session.id}", expiration_days=1)` — returns `(pat_record, raw_token)`.
2. Store `hash_pat(raw_token)` on `session.sandbox_token_hash`.
3. Pass `raw_token` to `setup_session_workspace()` as a new parameter (`api_key`).

The 1-day expiration is the safety net. Normal cleanup happens at session end. If cleanup fails (crash, orphaned pod), the PAT self-expires.

**File:** `backend/onyx/db/pat.py` — add helper

```python
def create_session_pat(
    db_session: Session,
    user_id: UUID,
    session_id: UUID,
    tenant_id: str | None = None,
) -> tuple[PersonalAccessToken, str]:
    """Create a short-lived PAT for a Craft session.

    Returns (pat_record, raw_token). The raw token is only
    available at creation time.
    """
    return create_pat(
        db_session=db_session,
        user_id=user_id,
        name=f"craft-session-{session_id}",
        expiration_days=1,
    )
```

#### 1d. PAT Revocation at Session Cleanup

**File:** `backend/onyx/server/features/build/session/manager.py`

In `cleanup_session_workspace()` (and any other session teardown path):

1. Load the session's `sandbox_token_hash`.
2. Look up the `PersonalAccessToken` by `hashed_token == sandbox_token_hash`.
3. Call `revoke_pat(db_session, pat.id, session.user_id)`.

Also in `delete_build_session__no_commit()` — if the session is being deleted, revoke its PAT first.

#### 1e. Periodic Orphan Sweep

**File:** `backend/onyx/server/features/build/sandbox/tasks/tasks.py`

Add a check to the existing `cleanup_idle_sandboxes_task()` Celery beat task (or add a new lightweight task):

- Query `BuildSession` rows where `sandbox_token_hash IS NOT NULL` and `status` is `COMPLETED` or last activity > 24h.
- For each, revoke the PAT if it hasn't already expired.
- Clear `sandbox_token_hash` on the session row.

This catches PATs that survived a failed cleanup.

#### 1f. PAT Visibility in UI

Session PATs are standard `PersonalAccessToken` rows. They appear in the user's PAT list (`GET /user/pats`). The naming convention `craft-session-{session_id}` makes them identifiable. No UI changes needed — the existing PAT list already shows name, created_at, and expiration. Users can see their session PATs but shouldn't need to manage them (auto-revoked on session end, auto-expired after 24h).

---

### 2. CLI Binary Bundling

#### 2a. Add onyx-cli to the Dockerfile

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile`

Add the onyx-cli Go binary to the sandbox image. The binary is built as part of the Onyx release and available as a build artifact.

```dockerfile
# Copy onyx-cli binary (built by the release pipeline)
COPY --chown=sandbox:sandbox onyx-cli /usr/local/bin/onyx-cli
RUN chmod +x /usr/local/bin/onyx-cli
```

The binary is on `$PATH` (`/usr/local/bin/`). No config file is needed — the CLI reads `ONYX_API_KEY` and `ONYX_SERVER_URL` from the environment (Part 1's agent-first design). The `configure` command is gated behind TTY and will error in the sandbox.

**Build pipeline update**: The CI/CD pipeline that builds the sandbox Docker image must also build the CLI binary (or copy it from the CLI build stage). This is a CI config change, not a code change. The CLI binary is a single static Go binary — no runtime dependencies.

#### 2b. Inject Environment Variables

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — `setup_session_workspace()`

After writing `opencode.json` and before starting the agent, write the CLI env vars into the session environment:

```bash
# Write CLI env vars to session .env file, sourced by opencode
echo "export ONYX_API_KEY={raw_pat_token}" >> {session_path}/.env
echo "export ONYX_SERVER_URL={internal_backend_url}" >> {session_path}/.env
```

**`ONYX_SERVER_URL`**: The internal Kube service address. This is a new config value:

**File:** `backend/onyx/server/features/build/configs.py`

```python
SANDBOX_ONYX_SERVER_URL = os.environ.get(
    "SANDBOX_ONYX_SERVER_URL",
    "http://api-server.onyx.svc.cluster.local:8080",
)
```

This is the address the sandbox uses to reach the Onyx backend. It's the internal Kube service, not the public URL. Set via environment variable on the api-server deployment for flexibility across environments.

**For local dev** (`SandboxBackend.LOCAL`): Use `http://localhost:8080` or whatever `WEB_DOMAIN` resolves to.

#### 2c. Method Signature Changes

`setup_session_workspace()` needs a new parameter:

```python
def setup_session_workspace(
    self,
    session_id: UUID,
    llm_config: LLMProviderConfig,
    use_demo_data: bool,
    user_name: str | None = None,
    user_role: str | None = None,
    user_work_area: str | None = None,
    # New: CLI auth
    api_key: str | None = None,  # Raw PAT token for ONYX_API_KEY
) -> None:
```

---

### 3. Company-Search Skill Creation

#### 3a. Skill Bundle Structure

**Directory:** `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/company-search/`

```
company-search/
├── SKILL.md.template
```

No `run.sh` — the agent calls `onyx-cli search` directly. The CLI is the tool. This is a deliberate departure from the earlier `search-requirements.md` design (which predated the CLI approach). The CLI handles auth, output formatting, error codes, and `--help` — wrapping it in a shell script would add a fragile indirection layer.

#### 3b. SKILL.md.template

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/company-search/SKILL.md.template`

```markdown
---
name: company-search
description: Search company knowledge using onyx-cli. Returns permissioned, citation-rich results from connected sources.
---

# company-search

Search the company's knowledge base — restricted to what the current user has
permission to see. Returns citation-rich results from connected data sources.

## Sources Available in This Session

{{AVAILABLE_SOURCES_SECTION}}

If a source you'd expect isn't listed, it isn't connected for this user — do not
assume it exists.

## Usage

```bash
onyx-cli search "<query>"
```

### Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--source` | Filter by source type (comma-separated) | `--source slack,google_drive` |
| `--days` | Only return results from the last N days | `--days 30` |
| `--limit` | Maximum number of results | `--limit 5` |
| `--json` | Output structured JSON instead of markdown | `--json` |

### Examples

```bash
# Search all sources
onyx-cli search "what is the sales process for enterprise deals?"

# Search only Slack and Google Drive, last 30 days
onyx-cli search "auth migration status" --source slack,google_drive --days 30

# Get fewer results for a focused lookup
onyx-cli search "PTO policy" --limit 3
```

## Output Format

Stdout is markdown with numbered citations like `[1]`, `[2]`, each followed by
the title, source, last-updated date, link, and document ID. Cite results by
their citation number when referencing them in your response.

## Error Handling

Non-zero exit codes indicate failures. The error message on stderr explains what
happened. Common issues:
- Authentication failure → PAT may be expired. This is a session issue — inform
  the user.
- Backend unreachable → transient network error. Retry once, then inform the user.
```

#### 3c. Template Rendering

**File:** `backend/onyx/server/features/build/sandbox/util/agent_instructions.py`

Add a new function to render the `{{AVAILABLE_SOURCES_SECTION}}` placeholder in `SKILL.md.template`:

```python
def render_company_search_skill_md(
    template_content: str,
    user: User,
    db_session: Session,
) -> str:
    """Render the company-search SKILL.md from its template.

    Substitutes {{AVAILABLE_SOURCES_SECTION}} with the user's
    accessible connector list.
    """
    available_sources = build_available_sources_section(user, db_session)
    return template_content.replace(
        "{{AVAILABLE_SOURCES_SECTION}}", available_sources
    )
```

The `build_available_sources_section()` function queries the user's accessible connectors and formats them:

```python
def build_available_sources_section(
    user: User,
    db_session: Session,
) -> str:
    """Build the available sources list for the company-search SKILL.md.

    Queries the user's accessible connector-credential pairs and formats
    a per-source-type summary with one-line descriptions.
    """
    from onyx.db.connector_credential_pair import (
        get_connector_credential_pairs_for_user,
    )

    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
    )

    if not cc_pairs:
        return "No connected sources available for this user."

    # Group by source type
    sources: dict[str, list] = {}
    for cc_pair in cc_pairs:
        source_name = cc_pair.connector.source.value
        if source_name not in sources:
            sources[source_name] = []
        sources[source_name].append(cc_pair)

    lines = []
    for source_name in sorted(sources.keys()):
        pairs = sources[source_name]
        description = _get_source_description(source_name, pairs)
        lines.append(f"- `{source_name}` — {description}")

    return "\n".join(lines)
```

The `_get_source_description()` function produces one-line descriptions:

```python
# Source descriptions — concise, agent-readable summaries
SOURCE_DESCRIPTIONS: dict[str, str] = {
    "google_drive": "Documents, spreadsheets, and presentations",
    "gmail": "Email conversations and threads",
    "slack": "Team messages and channel discussions",
    "linear": "Engineering and product tickets",
    "github": "Pull requests, issues, and code",
    "confluence": "Wiki pages and documentation",
    "jira": "Project tickets and issue tracking",
    "notion": "Notes, docs, and databases",
    "hubspot": "CRM contacts, deals, and company records",
    "fireflies": "Meeting transcripts and recordings",
    "salesforce": "CRM data and sales records",
    "zendesk": "Support tickets and help articles",
    "sharepoint": "Documents and intranet content",
    "bookstack": "Knowledge base articles",
    "discourse": "Forum discussions and topics",
    "productboard": "Product feedback and feature requests",
    "clickup": "Tasks and project management",
    "dropbox": "Files and shared folders",
    "asana": "Tasks and project workflows",
    "guru": "Knowledge cards and collections",
    "gong": "Sales call recordings and analysis",
    "freshdesk": "Support tickets and knowledge base",
    "document360": "Documentation and knowledge base articles",
    "loopio": "RFP responses and content library",
    "file": "Uploaded files",
    "web": "Web pages",
    "wikipedia": "Wikipedia articles",
    "requesttracker": "Request tracking tickets",
    "xenforo": "Forum posts and discussions",
    "ingestion_api": "API-ingested documents",
}


def _get_source_description(
    source_name: str,
    cc_pairs: list,
) -> str:
    base = SOURCE_DESCRIPTIONS.get(source_name, f"Data from {source_name}")

    # For sources with meaningful sub-scopes, include examples
    examples = _extract_scope_examples(source_name, cc_pairs)
    if examples:
        return f"{base} ({examples})"

    return base


def _extract_scope_examples(
    source_name: str,
    cc_pairs: list,
    max_examples: int = 5,
) -> str | None:
    """Extract sub-scope examples from connector config.

    For Slack: channel names. For Linear: team names.
    For GitHub: repo names. Returns None if not applicable.
    """
    names: list[str] = []

    for cc_pair in cc_pairs:
        config = cc_pair.connector.connector_specific_config or {}

        if source_name == "slack":
            channels = config.get("channels", [])
            names.extend(f"#{c}" for c in channels[:max_examples])
        elif source_name == "linear":
            teams = config.get("team_names", [])
            names.extend(teams[:max_examples])
        elif source_name == "github":
            repos = config.get("repositories", [])
            names.extend(repos[:max_examples])

    if not names:
        return None

    unique_names = list(dict.fromkeys(names))[:max_examples]
    result = ", ".join(unique_names)
    if len(unique_names) == max_examples:
        result += ", ..."
    return result
```

#### 3d. Skill Materialization in Session Setup

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — `setup_session_workspace()`

Currently, skills are symlinked:
```bash
ln -sf /workspace/skills {session_path}/.opencode/skills
```

This is a symlink to the baked-in skills directory. The `company-search` skill needs per-session rendering (for the user's source list), so we can't just symlink the template.

**Approach:**

1. Keep the symlink for all other skills (they're static).
2. After symlinking, copy the company-search template and render it:

```bash
# Symlink static skills
ln -sf /workspace/skills {session_path}/.opencode/skills

# Copy company-search skill (needs per-session rendering)
# The symlink is to the directory, so we need to break it for company-search
# Actually: change to copying ALL skills (simple, small overhead)
cp -r /workspace/skills/* {session_path}/.opencode/skills/
```

Wait — the symlink approach means we can't modify one skill without affecting all sessions. Better approach:

**Changed approach:** Copy skills instead of symlinking. The skills directory is small (a few SKILL.md files and scripts). Copying is fast and allows per-session customization.

```bash
mkdir -p {session_path}/.opencode/skills
cp -r /workspace/skills/* {session_path}/.opencode/skills/

# Render company-search SKILL.md from template
# The rendered content is passed from the backend as a base64-encoded string
echo "{base64_encoded_rendered_skill_md}" | base64 -d > {session_path}/.opencode/skills/company-search/SKILL.md
```

The `render_company_search_skill_md()` call happens server-side (in `setup_session_workspace()` in `manager.py`), and the rendered content is passed to the kubectl exec script. This avoids running Python inside the sandbox for rendering.

In the Dockerfile, the `SKILL.md.template` is left as-is at build time:

```dockerfile
COPY --chown=sandbox:sandbox skills/ /workspace/skills/
```

The template-to-rendered conversion happens at session setup time, not image build time.

---

### 4. Available Sources Injection

Covered in §3c above. The flow is:

1. `SessionManager.create_session__no_commit()` queries `get_connector_credential_pairs_for_user()`.
2. Calls `build_available_sources_section()` to produce the source list markdown.
3. Reads `SKILL.md.template` from the baked-in skill directory (or from a constant/embedded resource).
4. Calls `render_company_search_skill_md()` to substitute `{{AVAILABLE_SOURCES_SECTION}}`.
5. Passes the rendered SKILL.md content to `setup_session_workspace()`.
6. The workspace setup script writes the rendered content to `{session_path}/.opencode/skills/company-search/SKILL.md`.

The source list is a **snapshot at session creation**. Not refreshed mid-session. This matches the existing behavior of `build_knowledge_sources_section()` which scans `files/` at setup time.

**Edge case: User has no connected sources.** The rendered SKILL.md says:

```
No connected sources available for this user.
```

The agent should not hallucinate sources. The `company-search` skill is still registered (the user might have sources added mid-session that work even though they're not listed), but the agent is told there's nothing available.

---

### 5. Decommission File Sync

This is the largest change by line count. Every item here removes dead code — nothing is replaced, the replacement (onyx-cli search) is already wired up in §1–4.

#### 5a. Remove S3 File Sync Sidecar

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — `_create_sandbox_pod()`

Remove the file-sync sidecar container from the pod spec. Currently the pod has two containers:
1. **file-sync** (peakcom/s5cmd) — syncs S3 → `/workspace/files/`
2. **sandbox** (custom image) — the actual sandbox

Remove container (1). This also removes:
- The `files-volume` EmptyDir volume (or repurpose if sessions volume uses it)
- The `IRSA` / local AWS credential injection for the sidecar
- The `SANDBOX_FILE_SYNC_SERVICE_ACCOUNT` config reference
- The `SANDBOX_S3_BUCKET` config reference (verify no other consumers)

#### 5b. Remove `/workspace/files/` Directory

**File:** Dockerfile

Remove the `mkdir -p /workspace/files` line. The directory is no longer needed.

#### 5c. Remove Files Symlink from Session Setup

**File:** `kubernetes_sandbox_manager.py` — `setup_session_workspace()`

Remove the `files/` symlink creation:
```bash
# DELETE: ln -sf /workspace/files {session_path}/files
# DELETE: ln -sf /workspace/demo_data {session_path}/files
# DELETE: the entire filtered-symlink script for excluded paths
```

#### 5d. Remove `generate_agents_md.py`

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/docker/generate_agents_md.py`

Delete this file. It existed solely to populate `{{KNOWLEDGE_SOURCES_SECTION}}` by scanning `/workspace/files/` inside the container after S3 sync. With file sync gone, the placeholder is gone, and AGENTS.md is fully rendered server-side.

Also remove the `COPY` line in the Dockerfile that copies this script into the image.

#### 5e. Remove `build_knowledge_sources_section` and `CONNECTOR_INFO`

**File:** `backend/onyx/server/features/build/sandbox/util/agent_instructions.py`

Delete:
- `CONNECTOR_INFO` dict (lines 35–82)
- `_normalize_connector_name()` (lines 299–301)
- `_scan_directory_to_depth()` (lines 304–342)
- `build_knowledge_sources_section()` (lines 345–428)
- The `{{KNOWLEDGE_SOURCES_SECTION}}` replacement in `generate_agent_instructions()` (lines 498–505)
- The `files_path` parameter from `generate_agent_instructions()` (line 434)

Callers of `generate_agent_instructions()` that pass `files_path` must be updated to drop that parameter.

#### 5f. Remove `/workspace/files` Allowlist from OpenCode Config

**File:** `backend/onyx/server/features/build/sandbox/util/opencode_config.py`

Update the `external_directory` permission rules (lines 146–156):

```python
# Before:
"external_directory": (
    "allow"
    if dev_mode
    else {
        "*": "deny",
        "/workspace/files": "allow",
        "/workspace/files/**": "allow",
        "/workspace/demo_data": "allow",
        "/workspace/demo_data/**": "allow",
    }
),

# After:
"external_directory": (
    "allow"
    if dev_mode
    else {
        "*": "deny",
        "/workspace/demo_data": "allow",
        "/workspace/demo_data/**": "allow",
    }
),
```

Keep `/workspace/demo_data` rules if demo data survives (see §7).

#### 5g. Remove `PersistentDocumentWriter`

**File:** `backend/onyx/server/features/build/indexing/persistent_document_writer.py`

Delete this file. It contains `PersistentDocumentWriter` and `S3PersistentDocumentWriter` which sync indexed documents to the filesystem/S3 for sandbox consumption.

**Verify no other consumers first.** Check all imports/references:
- `session/manager.py` — uses `PERSISTENT_DOCUMENT_STORAGE_PATH` for constructing the knowledge path. Remove.
- `api/user_library.py` — uses `PersistentDocumentWriter` for user library file sync. **This is a separate concern** — user library uploads may still need persistent storage. If so, extract the user-library-specific parts before deleting.

**Decision:** The `user_library` use case (user-uploaded files like spreadsheets) must be audited. If user library files are only consumed via the `files/` directory in the sandbox, they should also move to the search path. If they have an independent consumption path (e.g., direct file reads via `attachments/`), the writer may need to be preserved for that path only.

Most likely: user library files are read via `attachments/` (user-uploaded session files), which is preserved. The `PersistentDocumentWriter`'s user_library path syncs library-level files (not per-session uploads) to the `files/` directory. With `files/` gone, this path is dead. Delete it.

#### 5h. Remove File-Sync Celery Tasks

**File:** `backend/onyx/server/features/build/sandbox/tasks/tasks.py`

Check for any Celery tasks that enqueue file-sync work. The `PersistentDocumentWriter` is called from `background/indexing/run_docfetching.py` — verify and remove the call site there too.

#### 5i. Remove `AGENTS.template-chris.md`

**File:** `backend/onyx/server/features/build/AGENTS.template-chris.md`

Delete if it exists (referenced in `search-requirements.md` as a file to remove).

---

### 6. Validation at Session Start

**File:** `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — `setup_session_workspace()`

After injecting the PAT and CLI env vars, run a validation check:

```bash
# Validate CLI can reach the backend and authenticate
ONYX_API_KEY="{raw_pat_token}" ONYX_SERVER_URL="{internal_url}" onyx-cli validate-config --json
```

Check the exit code:
- **0**: CLI is configured, backend is reachable, auth works. Proceed.
- **1 (NotConfigured)**: Env vars not picked up. Fatal — fail session setup with clear error.
- **3 (AuthFailure)**: PAT invalid or user deactivated. Fatal — fail session setup.
- **4 (Unreachable)**: Backend not reachable from sandbox. Fatal — fail session setup.

If validation fails, the session setup should abort and surface the error to the user (via the session creation API response), rather than letting the agent discover the tool is broken mid-task.

**Implementation:** The kubectl exec that runs the session setup script should check the validation exit code and return it. `SessionManager` interprets the failure and raises an `OnyxError` with a descriptive message.

---

### 7. Demo Data Path

The `demo_data/` directory is baked into the Docker image and symlinked into sessions when `demo_data_enabled=True`. It does NOT go through the S3 file-sync path — it's a static directory in the image.

**Impact of file-sync removal on demo data:**

- The `files/` symlink for demo mode (`ln -sf /workspace/demo_data {session_path}/files`) is removed.
- Demo data was consumed by the agent via `find`/`grep` over `files/`.
- With `files/` gone, the agent can't read demo data via file operations.

**Decision:** Demo data moves to the search path too. If demo data is indexed in Vespa (which it should be for a demo to work with the new search tool), it's searchable via `onyx-cli search`. If demo data has a separate ingestion path that puts it into Vespa, it works automatically. If demo data was ONLY consumed via the `files/` directory and never indexed, then demo data breaks.

**Action items:**
1. Verify whether demo data is indexed in Vespa. If yes: demo data works with the search tool, no changes needed beyond removing the `files/` symlink.
2. If demo data is NOT indexed: either index it (preferred — makes demo consistent with real usage) or preserve the `files/` symlink for demo mode only as a temporary measure.
3. Remove the `/workspace/demo_data` allowlist from `opencode_config.py` if demo data no longer needs direct file access.

---

### 8. AGENTS.template.md Rewrite

**File:** `backend/onyx/server/features/build/AGENTS.template.md`

Replace the current template. Key changes:

1. **Delete** the entire "Knowledge Sources" section (lines 75–85) and the `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder.
2. **Delete** the "Document Format" note about JSON files.
3. **Delete** the "read-only files/ directory" note.
4. **Rewrite** "Step 1: Information Retrieval" to point at the `company-search` skill.
5. **Keep** everything else (Configuration, Environment, Skills, Behavior Guidelines, Outputs, Questions to Ask).

New "Information Retrieval" section:

```markdown
### Step 1: Information Retrieval

1. **Search** company knowledge using the `company-search` skill. This is your
   only path to company context — there is no `files/` directory. Run
   `onyx-cli search "<query>"` and read the returned markdown; cite results by
   their citation number when you reference them in your response.
2. Read the `company-search` SKILL.md for available sources and usage examples.
3. **Iterate** — run additional searches to gather enough context. Refine queries
   based on what you learn from initial results.
4. **Summarize** key findings before proceeding to output generation.

**Tip**: Use `--source` to narrow results to specific connectors and `--days`
to focus on recent content.
```

Remove the old "Tip" about `find`, `grep`, `glob`.

---

### 9. Local Development (SandboxBackend.LOCAL)

**File:** `backend/onyx/server/features/build/sandbox/manager/directory_manager.py` (and local sandbox manager)

The local sandbox manager also needs the same changes:
- Mint a session PAT and inject `ONYX_API_KEY` + `ONYX_SERVER_URL` as env vars (or write them to the session workspace).
- Copy the company-search skill with rendered SKILL.md.
- Remove the `files/` symlink creation.
- The onyx-cli binary must be installed on the developer's machine and on `$PATH` (or installed into the local sandbox workspace).

For local dev, `ONYX_SERVER_URL` defaults to `http://localhost:8080` (or whatever the local backend is).

---

## Execution Order

The implementation should proceed in this order to minimize broken states:

1. **Database migration** (§1a–1b) — add `sandbox_token_hash` column. No runtime impact.
2. **PAT lifecycle** (§1c–1e) — mint PATs at session creation, revoke at cleanup. Sessions now have PATs but sandbox doesn't use them yet.
3. **CLI bundling + env injection** (§2) — add CLI to image, inject env vars. CLI is available but not yet used by the agent.
4. **Skill creation + AGENTS.md rewrite** (§3, §4, §8) — add company-search skill, update AGENTS.md. Agent now has both paths available (search + files).
5. **Startup validation** (§6) — verify CLI works before agent starts.
6. **Decommission file sync** (§5) — remove files/, S3 sidecar, PersistentDocumentWriter. This is the breaking change — do it last so we can test search works before removing the fallback.
7. **Demo data assessment** (§7) — handle based on findings.

Steps 1–5 can be shipped incrementally. Step 6 is the cutover — ship it when confident search works end-to-end.

---

## Tests

### External Dependency Unit Tests

**File:** `backend/tests/external_dependency_unit/craft/test_session_pat_lifecycle.py`

Tests that require real Postgres + Redis but no running Onyx services:

- **PAT minting**: Create a BuildSession, verify a PAT is minted, verify `sandbox_token_hash` is set on the session.
- **PAT revocation on cleanup**: Clean up a session, verify the PAT is revoked (`expires_at <= now`).
- **PAT expiration**: Create a session PAT with 1-day expiry, verify the expiration is set correctly.
- **Orphan sweep**: Create a session PAT, mark the session as COMPLETED, run the sweep, verify PAT is revoked.

**File:** `backend/tests/external_dependency_unit/craft/test_company_search_skill.py`

- **Source list rendering**: Create test connector-credential pairs for a user, call `build_available_sources_section()`, verify the output lists the correct sources with descriptions.
- **Empty sources**: User with no connectors → output says "No connected sources available."
- **Sub-scope examples**: Create a Slack connector with channel config, verify channels appear in the description.
- **SKILL.md rendering**: Verify `render_company_search_skill_md()` substitutes `{{AVAILABLE_SOURCES_SECTION}}` correctly.

### Unit Tests

**File:** `backend/tests/unit/onyx/server/features/build/test_agent_instructions_rewrite.py`

- **AGENTS.md no longer references files/**: Render the new `AGENTS.template.md` with `generate_agent_instructions()`, verify the output does not contain "files/", "JSON documents", "find files", or `{{KNOWLEDGE_SOURCES_SECTION}}`.
- **AGENTS.md references company-search**: Verify the output contains "onyx-cli search" and "company-search".

### Integration Tests

**File:** `backend/tests/integration/tests/craft/test_craft_search_e2e.py`

End-to-end test against a running Onyx deployment:

- **Full round-trip**: Create a Craft session → verify PAT is minted → run `onyx-cli search` inside the sandbox → verify results come back → end session → verify PAT is revoked.
- **Cross-tenant isolation**: User A in tenant 1 searches → does not see docs from tenant 2.
- **Validation at startup**: Create a session → verify `onyx-cli validate-config` succeeds inside the sandbox.

### Manual Smoke Tests

Before merging:

1. Run a real Craft session locally. Watch the agent call `onyx-cli search`. Confirm it cites results from the live Onyx index.
2. Confirm `find files/` returns nothing (corpus path is gone).
3. Run the same query through regular Onyx chat search and through `onyx-cli search` for the same user — top results should overlap heavily.
4. Confirm a search by user A in tenant 1 cannot see docs ingested by user B in tenant 2.
5. Start a session with no connected sources — verify SKILL.md says "No connected sources available" and the agent doesn't hallucinate sources.
6. Kill a session without clean shutdown — verify the PAT expires within 24 hours.
