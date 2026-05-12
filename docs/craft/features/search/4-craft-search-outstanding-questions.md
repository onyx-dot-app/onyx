# Craft Search Integration — Design Decisions for Review

> Context: [search-design.md](search-design.md) (Part 4) | Implementation plan: [4-craft-search.md](4-craft-search.md)

This document covers the non-obvious design decisions in the Part 4 implementation plan. Each section explains what we're doing, what alternatives we considered, and why we chose this approach. Feedback welcome on any of these.

---

## 1. PATs as the sandbox auth mechanism

### What we need

The Craft sandbox needs to call `POST /api/search` (and eventually other Onyx APIs) authenticated as the session's user. The CLI already authenticates via `Authorization: Bearer onyx_pat_...` using the `ONYX_PAT` env var.

### Decision: Use PATs

The sandbox gets a standard Personal Access Token scoped to the user. The same token type that external API consumers use.

### Why PATs over a custom session token

The earlier `search-requirements.md` design used a custom `sandbox_token` on `BuildSession` with a dedicated auth dependency. We moved to PATs because:

- The CLI already authenticates via PAT — a custom token would need either a new CLI auth mode or a backend translation layer
- PATs carry user identity and will get permission scopes when the Permissions system ships
- No new auth code path to build or maintain

---

## 2. Storing the PAT encrypted at rest

### The problem

PATs are hashed (SHA256) in the `personal_access_token` table — the raw token is only available at creation time and can't be recovered. But the sandbox needs the raw token injected on every session setup and resume (after sleep, the old pod is dead and the env var is gone).

Naive approach: mint a new PAT on every session setup. This causes accumulation — a daily user generates ~1000+ revoked PAT rows per year. Soft-delete (our audit pattern) means they never go away.

### Decision: One PAT per user, raw token stored encrypted on the Sandbox row

```python
# PersonalAccessToken — distinguish user-created from system-managed PATs
pat_type: Mapped[str] = mapped_column(String, nullable=False, server_default="user")

# Sandbox — store raw PAT encrypted for re-injection on pod provisioning
encrypted_pat: Mapped[SensitiveValue[str] | None] = mapped_column(
    EncryptedString(), nullable=True
)
```

- **One PAT per user** with `pat_type="craft"`, not per session. The security boundary is the pod, which is already one-per-user. Per-session PATs don't add security within the same pod. The `pat_type` column on `PersonalAccessToken` explicitly distinguishes Craft PATs from user-created ones — no name-prefix conventions. `GET /user/pats` filters by `pat_type == "user"` so Craft PATs are invisible to the user.
- **Stored encrypted** using our existing `EncryptedString` column type (same as LLM API keys, connector credentials, OAuth tokens). Decrypted at pod provisioning time.
- **Injected as a pod-level env var** (`ONYX_PAT`) in the K8s pod spec at provisioning time. All sessions in the pod inherit it automatically — no per-session token injection or shared files. Pods are terminated after 1 hour of inactivity, so the PAT never expires mid-pod (30-day expiry >> 1-hour idle timeout). On re-provisioning, `_ensure_sandbox_pat()` runs again and sets the env var on the new pod.
- **30-day expiry** as a safety net. At each pod provisioning, check if the stored PAT is still valid. If expired (user was away for 30+ days), mint a new one. No proactive rotation, no revocation on sleep or termination — the PAT and `encrypted_pat` are preserved across all sandbox state transitions.
- **Future-compatible with egress proxy.** The `encrypted_pat` column on `Sandbox` is the single source of truth. Today it's read at pod provisioning and set as an env var. When the egress interception proxy ships (Craft V1 project #4), the proxy reads from the same column and injects credentials server-side — the env var goes away, the sandbox never sees the raw token, and the DB storage is unchanged.

### Why not mint-per-session?

| Approach | PAT rows per user/year | Complexity | Security |
|----------|----------------------|------------|----------|
| **Per-session mint** | ~1000+ (accumulating revoked rows) | Simple mint/revoke, but needs cleanup job or accepts bloat | Tighter per-session scope, but all sessions share one pod anyway |
| **Per-user encrypted** (chosen) | 1 active + ~12 revoked (one per monthly rotation) | Needs encrypted storage column + migration | Same effective security — one pod = one trust boundary |

The per-user approach has ~100x fewer PAT rows and eliminates all the lifecycle complexity around sleep/resume. The cost is one `EncryptedString` column — infrastructure we already have.

### Delivery mechanism: pod-level env var

The raw token is set as `ONYX_PAT` in the K8s container env vars at pod creation time. All sessions in the pod inherit it automatically. Pods don't outlive the PAT — the 1-hour idle timeout terminates the pod long before the 30-day expiry. Re-provisioning gives a fresh chance to set the env var.

---

## 3. User library file delivery after sidecar removal

### Decision: Shared volume + kubectl exec sync

The file-sync sidecar is removed (search replaces connector document access). But user library files — raw binaries (spreadsheets, PDFs) the agent opens with Python libraries — aren't indexed in Vespa and can't be replaced by search. They still need direct file access.

Replace the sidecar with a shared `/workspace/user_library/` directory at the pod level. Sync via one-shot `kubectl exec` (running `s5cmd sync`) triggered at:
- **Session setup/resume** — populates the directory, catching any files uploaded while the pod was sleeping
- **After each upload** — a Celery task fires a kubectl exec to sync the new file immediately

```
User uploads spreadsheet via API
  └─ write_raw_file() → S3  (existing path, unchanged)
  └─ dispatch SYNC_USER_LIBRARY_FILES Celery task
      └─ kubectl exec: s5cmd sync s3://.../user_library/ /workspace/user_library/
  └─ file appears in sandbox immediately
```

Sessions access files at `/workspace/user_library/` directly — it's a pod-level shared directory, no per-session symlink needed.

### Why this over alternatives

| Approach | Pros | Cons |
|----------|------|------|
| **Shared volume + kubectl exec** (chosen) | Storage efficient (one copy shared across sessions), handles mid-session uploads, no sidecar process, established kubectl exec pattern | Couples backend to K8s exec API, small race window during sync |
| **Download into each session at setup** | Simple, isolated per-session | Duplicated storage (N copies for N sessions), slow setup for large libraries, mid-session uploads need separate push mechanism |
| **Keep the sidecar for user_library only** | No code changes to sync path | Keeps a persistent container alive for a lightweight job. The sidecar was removed because its primary purpose (connector sync) is dead — keeping it for a secondary purpose is architectural debt. |

### What stays, what goes in PersistentDocumentWriter

`PersistentDocumentWriter` currently has two write paths:

| Method | Purpose | After refactor |
|--------|---------|----------------|
| `write_documents()` | Serialize indexed connector docs to JSON files | **Dead.** Search replaces file access. Remove along with `serialize_document()` and path builder helpers. |
| `write_raw_file()` | Store user-uploaded binaries (xlsx, pptx, etc.) to S3 | **Alive.** User library uploads still need S3 storage. Keep this method and the factory. |

`SANDBOX_S3_BUCKET` config stays — both the user library write path and the new kubectl exec sync depend on it.

The sync is idempotent — `s5cmd sync` compares checksums and only transfers changed files. If the pod is evicted mid-sync, the next sync recovers cleanly. If the pod is sleeping when an upload happens, files accumulate in S3 and are pulled on resume.

### Open question: Docker Compose setups

The shared volume + kubectl exec approach is K8s-native. How user library file delivery works for Docker Compose setups is unclear and depends on how we implement Docker Compose sandboxes — this is out of scope for this plan but needs resolution before Craft ships on non-K8s infrastructure.

