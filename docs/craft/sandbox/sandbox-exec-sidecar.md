# Move sandbox filesystem ops off `kubectl exec` onto the signed sidecar

## Issues to Address

`KubernetesSandboxManager` drives in-pod work through 14 `k8s_stream`
(`connect_get_namespaced_pod_exec`) call sites. Most are filesystem operations
implemented as interpolated shell scripts and parsed via stdout sentinels. This
has three recurring problems:

- **Shell-injection surface:** f-string scripts with hand-rolled quoting, e.g.
  `agent_instructions.replace("'", "'\\''")` in `setup_session_workspace` and
  `_regenerate_session_config`, and `content.replace("'", ...)` in
  `write_sandbox_file`.
- **Stdout-sentinel parsing:** behavior is derived from substring matches like
  `"WORKSPACE_FOUND"`, `"ERROR_NOT_FOUND"`, `"DELETED"`, `"WRITE_OK"`,
  `"EXISTS"`. This is the exact bug class that caused the
  `"EXISTS" in "NOT_EXISTS"` substring failure in snapshot restore.
- **Transport complexity:** exec runs over SPDY/WebSocket, which forced the
  dual-`ApiClient` workaround (`_rest_api_client` vs `_stream_api_client`,
  lines ~422-436) to avoid the streaming monkeypatch leaking into REST calls.

The codebase already has the better channel: a signed HTTP sidecar daemon
(`sandbox_daemon/server.py`, port 8731, Ed25519-verified) that shares the
`workspace` and `managed` volumes read-write and already serves `/push`,
`/snapshot/create`, `/snapshot/restore`. Snapshots and file pushes were already
migrated off exec onto it. This plan finishes that migration for the remaining
filesystem ops, hardens the small residual that must stay as exec, and adopts
the **complementary split**: sidecar owns all filesystem/compute; exec is
retained only for in-sandbox-container process control.

## Important Notes

- **Residual exec is exactly the Next.js dev-server lifecycle — 3 call sites:**
  start (in `setup_session_workspace` line ~1668 and `restore_snapshot` line
  ~2003) and kill (in `cleanup_session_workspace` line ~1737). The dev server
  must run as a long-lived process *in the sandbox container* (it serves traffic
  on that container's exposed port); the sidecar can't host or signal it because
  `share_process_namespace=False`. Everything else moves to the sidecar.
- **`bun install` can move to the sidecar.** The sidecar runs the same image, so
  it has `bun`, and `node_modules` lands on the shared `workspace` volume. Only
  the dev-server *process* is container-bound — not the install. This shrinks
  residual exec to just start/stop.
- **Audit of all 14 sites:**
  - Filesystem → new sidecar endpoints: `session_workspace_exists` (3),
    `list_session_workspaces` (4), `_regenerate_session_config` (6),
    `list_directory` (7), `read_file` (8), `_ensure_agents_md_attachments_section`
    (10), `delete_file` (12), `write_sandbox_file` (13), `get_upload_stats` (14),
    and the filesystem halves of `setup_session_workspace` (1) and
    `cleanup_session_workspace` (2).
  - `upload_file` (11) is the only stdin-streaming exec; it tar-extracts into
    `attachments/` — i.e. exactly what `/push` already does. Reuse/extend the
    existing `/push` endpoint rather than adding a new one.
  - `generate_pptx_preview` (9) runs `python preview.py` (soffice/pdftoppm).
    Tools are in the shared image so it *can* run in the sidecar, but it is
    CPU-heavy and the sidecar is capped at 500m CPU. Decision point: give it its
    own sidecar endpoint with bumped sidecar limits, or leave it as a hardened
    exec in the sandbox container. Recommend sidecar endpoint + raise the sidecar
    CPU limit, to keep the "no filesystem exec" invariant clean.
  - Residual (process control): the dev-server start/stop in sites 1, 2, 5.
- **Honest tradeoffs of the complementary split** (chosen over sidecar-only):
  because exec remains for the dev server, two benefits are NOT realized —
  `pods/exec` stays in the sandbox-manager RBAC Role
  (`deployment/helm/charts/onyx/templates/sandbox-rbac.yaml`; K8s can't scope
  exec by command), and the dual-`ApiClient` workaround stays (it's required as
  long as any `k8s_stream` exists). Both shrink to serving only 3 call sites. A
  later sandbox-container control endpoint could remove them entirely if desired.
- **Wire-schema location:** request/response models go in
  `sandbox_daemon/contract.py` (the daemon imports `sandbox_daemon.contract`; the
  api-server imports the full
  `onyx.server.features.build.sandbox.image.sandbox_daemon.contract` path). This is
  the existing shared-contract pattern — both ends stay in sync.
- **Reuse the existing client plumbing** on the api-server side:
  `_signed_sidecar_headers` + `_sandbox_pod_hosts` (Service FQDN, then pod-IP
  fallback for out-of-cluster CI), exactly as `create_snapshot` /
  `write_files_to_sandbox` do today.
- **Sidecar requires no new privilege** — it already mounts both volumes RW.
- **Image build:** the residual exec uses a baked script (below), so the sandbox
  image (`image/Dockerfile`) changes — coordinate the matching app/sandbox
  image tag, and note the daemon endpoints also ship in that image.

## Implementation Strategy

1. **Add typed models** to `sandbox_daemon/contract.py` for each new operation
   (session setup, cleanup, list-sessions, exists, list-directory, read-file,
   delete-file, write-file, upload-stats, ensure-attachments, regenerate-config,
   pptx-preview). Structured request bodies + JSON responses replace every
   stdout sentinel.

2. **Add signed endpoints** to `sandbox_daemon/server.py`, each guarded by the
   existing `_verify_signature` pattern. Implement the filesystem logic in the
   daemon (it can `import` and reuse helpers rather than shell out). Extend
   `/push` (or add a sibling) to cover `upload_file`'s tar-extract-with-collision
   semantics. Decide pptx-preview placement per the note above.

3. **Add a baked dev-server script** to the image, e.g.
   `/workspace/session-dev-server.sh start|stop <session_path> <port>`,
   containing today's `_build_nextjs_start_script` logic plus the PID-kill from
   cleanup. Exec it with **positional args only** — no interpolation. This
   removes the last f-string exec and the `agent_instructions` quoting (AGENTS.md
   is now written via the sidecar).

4. **Rewrite the api-server methods** to call the sidecar over `httpx`
   (reusing `_signed_sidecar_headers` / `_sandbox_pod_hosts`) and to return
   typed results. Split `setup_session_workspace` into: sidecar `/session/setup`
   (mkdir/cp/symlink/AGENTS.md/bun-cache/bun-install) → hardened exec
   `session-dev-server.sh start`. Split `cleanup_session_workspace` into:
   hardened exec `session-dev-server.sh stop` → sidecar `/session/cleanup`
   (`rm -rf`). `restore_snapshot` keeps the hardened dev-server-start exec and
   moves `_regenerate_session_config` to the sidecar.

5. **Delete** `_parse_ls_output` stdout parsing, the sentinel checks, and the
   per-method inline scripts as their callers move to typed responses. Keep
   `_stream_api_client` and the 3 residual exec call sites.

6. **Leave RBAC unchanged** (`pods/exec` still needed for the dev-server). Add a
   code comment at the residual exec sites noting they are the only remaining
   exec users and why.

## Tests

- **Integration test (kind, primary):** for a provisioned sandbox, exercise the
  migrated round-trips end-to-end through the sidecar — `setup_session_workspace`
  then `session_workspace_exists`/`list_session_workspaces`, `write_sandbox_file`
  + `read_file`, `upload_file` + `get_upload_stats` + `delete_file`,
  `list_directory`, and `restore_snapshot`. Assert the dev server still comes up
  (residual exec path) and the webapp URL responds.
- **Daemon unit tests (sidecar):** for each new endpoint, test signature
  rejection (bad/expired signature → 401) and the success/not-found/error paths
  return structured status codes — explicitly covering the cases that used to be
  stdout sentinels (e.g. missing file → 404, not a substring match).
- **Regression guard:** a test asserting `session_workspace_exists` returns the
  correct boolean for both an existing and a non-existing session — the
  `"EXISTS" in "NOT_EXISTS"` bug class — now via a typed response.

Prefer the kind integration test as the backbone; add daemon unit tests only for
the signature/error-path logic that integration can't cleanly force.
