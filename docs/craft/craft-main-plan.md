# Craft V1 Main Plan

## Objective

Craft is Onyx's "AI coworker" surface: an agent that knows company context and finishes work end-to-end inside an isolated sandbox. The pieces already exist — a separate `/craft/v1` UI, `/api/build` routes, OpenCode-based sandbox execution, artifact persistence, file uploads, built-in sandbox skills, and Kubernetes sandbox isolation. V1's job is to integrate those pieces into a coherent, enterprise-approvable product without rebuilding the runtime.

The bar for V1: a user (or scheduled trigger) can give Craft a prompt, the agent uses Onyx-grade permissioned retrieval to read company knowledge, can call external systems through an Onyx-controlled boundary that injects secrets and gates writes behind approvals, and produces durable artifacts with a clear audit trail.

## Enhancements

V1 covers nine product-level enhancements:

1. **Onyx hybrid search inside the sandbox** — replaces the old `files/` corpus sync with a first-party search tool that mirrors the regular Onyx search experience, scoped to the running user's permissions.
2. **Real sandbox isolation** — adds a docker-compose backend for self-hosted, alongside the existing Kubernetes path for cloud. The current `local` filesystem mode stays as a dev backend only.
3. **First-class skills** — DB-backed, versioned, shareable skill bundles (built-in + custom) that admins can manage and users can pin to sessions or triggers.
4. **Egress interception layer for secrets and external access** — sandbox HTTP/S egress is forced through an Onyx-managed proxy that injects credentials server-side for allowlisted upstream services. Sandbox never sees raw tokens.
5. **OAuth for external apps** — admins define "Apps" the agent can ask the user to authenticate with; per-user access tokens are stored in the proxy layer and injected on the user's behalf when the agent calls those APIs. Mirrors the existing Onyx OAuth-for-actions (custom tools) flow.
6. **Approvals** — first-class workflow for gating risky agent actions (external writes, deliveries, destructive ops). Enforcement lives in backend/proxy paths; review and notifications live in the Craft app.
7. **Scheduled triggers** — saved prompts that run on a schedule with durable run records, artifact delivery, timeouts, and approval-aware pause/resume.
8. **Shared admin UI** — admin UI for Craft enablement, skills, intercepted services/secrets, OAuth apps, approval policies, and trigger oversight.
9. **Run audit and observability** — compact run/audit layer for governing background work: which searches ran, which upstreams were called, which approvals fired, which skills were used.

## Out of Scope

Intentionally deferred for V1 and why:

- **Connector file sync into the sandbox** — Onyx search gives us permissioned retrieval without shipping the corpus into the sandbox.
- **One-click integration installers in Craft UI** — admins should configure intercepted services explicitly; magic installers add risk without product validation.
- **Dedicated Craft config for LLMs/connectors/data sources** — the main admin panel stays the source of truth. Craft only surfaces availability/status.
- **Demo dataset / demo-data mode** — V1 starts from real user/org context.
- **Use-case-specific UIs** (sales/support/eng/exec) — too narrow before the core platform settles.
- **Rebuilding the agent runtime** — OpenCode is good enough; we keep a clean boundary so it can be swapped later.
- **Merging Craft into the main chat surface** — Craft stays at `/craft/v1` to keep UX and concerns separated.
- **MCP support.** - prefer using an intercept layer + skills + raw API calls.
- **Event triggers** (Slack, webhooks, calendar, file changes) — scheduled-only for V1; event triggers wait.
- **Renaming backend `build/` modules to `craft/`** — broad rename adds migration risk without product value.
- **Skill editing in the browser** — admins upload bundles; in-browser authoring is later.

## Project Breakdown

Nine projects, scoped to be worked on largely independently. Some entanglement (OAuth and approvals both touch interception; triggers depend on approvals) is expected but called out below.

### 1. Onyx Search Tool for Craft

Expose Onyx hybrid search to OpenCode as a first-party HTTP tool that exactly mirrors the regular Onyx app search tool. Sandbox calls `onyx_search` with a session-scoped token; backend resolves token → user/tenant/session, runs the existing Onyx hybrid search path as that user, returns compact results with citation metadata. Update `AGENTS.template.md` so the agent uses Onyx search for company knowledge and uploaded files only as explicit session input. Remove all references to the legacy `files/` company-knowledge directory.

**Key decisions:** purpose-built HTTP tool (not MCP), exact behavioral parity with the regular search tool, search runs as the session/trigger owner.

Detail doc: `search.md` (to be written).

### 2. Docker-Compose Sandbox Backend

Add a `docker` sandbox backend alongside `local` (dev only) and `kubernetes` (cloud). Backend controls Docker directly — no separate runner service. Reuses the same sandbox image family as Kubernetes so skills/templates/OpenCode/LibreOffice/Python/Node behave identically across deployments. Local snapshots use a docker volume or the existing file-store abstraction. Self-hosted Craft docs should require `docker` or `kubernetes`; `local` is explicitly dev-only.

**Key decisions:** direct Docker control from the backend (no runner microservice), shared image family across docker/k8s, `local` retained for dev but not marketed as secure.

Detail doc: `sandbox-backends.md` (to be written).

### 3. Skills System

DB-backed skills with versioned bundles stored in the existing file store and materialized into `.opencode/skills` at sandbox setup. Admins can enable/disable built-ins, upload custom bundles, and grant org-wide or per-group. Users pin skills to sessions or triggers. Built-ins for V1: presentation/deck, document/report, dashboard/web app, image generation (if provider configured), Onyx search/research skill. Skill shape stays compatible with Codex/OpenCode skills so the future "skills library" is mostly distribution + trust metadata, not a new runtime.

**Key decisions:** built-ins are seeded into the DB so built-in and custom skills share one admin/selection path; no in-browser skill editing in V1; no second plugin ecosystem.

Detail doc: `skills.md` (to be written).

### 4. Egress Interception & Secrets

The interception proxy is the only component that can read decrypted secrets and the first enforcement point for outbound writes. Sandbox egress is routed via `HTTP_PROXY`/`HTTPS_PROXY` to the Onyx proxy; the Onyx CA cert is trusted in the sandbox image; direct external egress is blocked. Skills call normal upstream URLs (e.g. `https://api.linear.app/graphql`); proxy resolves session → grants → policy, classifies the request (read/write/delivery/destructive/unknown), injects credentials server-side for allowlisted requests, and forwards. Non-secret internet access defaults to pass-through.

Models: `CraftSecret`, `CraftInterceptedService`, `CraftInterceptedServiceGrant`, `CraftEgressPolicy`.

**Key decisions:** proxy-environment interception (not transparent network appliance) for V1; sandbox never receives raw tokens; ambiguous requests classified `UNKNOWN` and require approval by default; interception is the secrets boundary AND the external-write approval enforcement point.

Detail doc: `interception.md` (to be written). Has tight coupling with **Approvals** — interception is where most write approvals are enforced.

### 5. OAuth for External Apps

Admins can register "Apps" (e.g. Linear, HubSpot, Google Calendar, custom OAuth-capable APIs) that the Craft agent can prompt the user to authenticate with. The OAuth flow runs in the Craft UI — never inside the sandbox. The retrieved access/refresh tokens are stored encrypted in the proxy/credential layer, scoped per-user and per-app. When the agent calls a registered App's API, the egress proxy resolves session → user → App grant and injects the user's access token server-side, refreshing it as needed. Should mirror the existing Onyx OAuth-for-actions (custom tools) flow for admin configuration shape (client id/secret, auth/token URLs, scopes, redirect URI) and for the user-consent UX.

Per-app definition includes upstream base URL(s), allowed methods/path prefixes, scopes, and approval policy — same shape as a `CraftInterceptedService`, but with per-user OAuth credentials instead of an org-wide secret. Admin can grant Apps org-wide or per-group; the user must still complete the OAuth handshake before the agent can act on their behalf. If a user-bound token is missing or expired and unrefreshable, the agent's call returns a structured "needs auth" response that the Craft UI surfaces as a connect-app prompt.

**Key decisions:** OAuth handshake happens in the main Craft UI, not the sandbox; tokens are stored in the proxy/credential layer and never reach the sandbox; per-user scoping (vs. the org-wide secrets in project 4); reuse the existing Onyx custom-tool OAuth implementation patterns wherever possible rather than building a parallel system; refresh handled by the proxy on demand.

Detail doc: `oauth-apps.md` (to be written). Builds directly on **Egress Interception** (uses the same proxy + grant + classification path) and inherits **Approvals** for any write requests through OAuth-backed Apps.

### 6. Approvals

First-class approval primitive for risky Craft actions: external writes, deliveries, destructive ops, unknown actions, scheduled runs that hit gated actions. Enforcement lives in two places: the egress proxy (for outbound HTTP) and Craft orchestration (for first-party publish/delivery). Approval review and notifications live in the Craft app — session banner for interactive runs, run-detail panel for scheduled runs, an inbox for cross-session pending items. Approved requests replay through the proxy with an idempotency key so retries don't duplicate writes.

**Key decisions:** approvals are in scope for V1; enforcement in backend/proxy paths only (prompts and OpenCode permissions are guidance, not boundary); session/trigger owner can approve their own writes by default with admin override; encrypted request snapshots + idempotency keys for safe replay; no Slack/email notification dependency in V1 (skill-based later).

Detail doc: [`approvals.md`](approvals.md).

### 7. Scheduled Triggers

Saved Craft prompts on a schedule. Three schedule forms: run-once, simple interval, advanced cron. Each scheduled run creates a brand-new Craft session, materializes attachments and skills, runs the agent through a backend runner (not SSE-dependent), persists artifacts and a summary, and notifies the Craft app. Beat task claims due triggers atomically (`SELECT FOR UPDATE SKIP LOCKED`), enqueues `run_craft_trigger` with `expires=`. Default concurrency is `SKIP_IF_RUNNING` for recurring; `QUEUE_ONE` for run-once and run-now. Sandbox operation leases prevent multiple agent runs from sharing one sandbox.

**Key decisions:** every scheduled run gets a fresh session (no reuse); scheduled-only for V1 (no event triggers); explicit timeout logic in the task body (Celery time limits don't work with thread pools); approval-waiting runs release sandbox capacity so humans aren't blocking CPU.

Detail doc: [`triggers.md`](triggers.md). Depends on **Approvals** for the `WAITING_FOR_APPROVAL` state and on **Interception** for write gating.

### 8. Shared admin UI

Admin and user surfaces for managing Craft itself, all in the main app:

- Admin Craft page: enable Craft, manage built-in/custom skills, manage intercepted services + secrets, manage OAuth Apps, manage approval policies, set sandbox backend, view org usage.
- User-facing Craft pages: approval inbox, triggers list/editor, run history, connected-apps page (manage OAuth grants and revoke them).
- Read-only availability/status panels (model, search, skills, intercepted services) so users understand why a run can or can't start.
- Existing admin pages remain the source of truth for LLM providers, connectors, users/groups, and document ingestion. Craft does **not** add a parallel config surface for these.

**Key decisions:** Craft UI stays operational, not marketing; remove the existing demo-data UI and backend path; do not duplicate connector/LLM/user admin in Craft.

Detail doc: `admin-ui.md` (to be written).

### 9. Run Audit & Observability

Compact run/audit layer on top of existing session/message/artifact records (which already give us the interactive replay). For each run, persist summary metadata (user/tenant, session id, trigger id, model, selected skills/services, approval counts, sandbox id/backend/lease, run source, start/end/duration, artifact ids, summary) plus indexed event records for: Onyx search calls, intercepted upstream calls, approval requests, skill usage, admission/limit decisions, notification attempts. Optimized for admin/debug queries ("which runs used HubSpot last week?", "why did this trigger skip?", "which writes were approved?"), not conversation rendering.

**Key decisions:** do not duplicate the full conversation transcript; never store raw secrets; redact prompts/tool args using existing privacy patterns; full request snapshots for approval replay are encrypted and short-lived.

Detail doc: `audit.md` (to be written).

## Smaller Improvements

- Test different agent harnesses (Pi vs OpenCode)
- Nuke ACP (while maintaining harness flexibility)
- Powerpoint generation enhancements

## Other Important Notes

- **Treat existing Craft/Build code as the foundation.** `backend/onyx/server/features/build/` already owns sessions, messages, artifacts, sandbox setup, uploads, and OpenCode streaming. `web/src/app/craft/v1/` already provides the separate UI. Don't rewrite — integrate.
- **No backwards compatibility requirement.** Craft was alpha, so losing existing sessions, artifacts, sandboxes, or other Craft state is acceptable if it simplifies the V1 implementation. Preserve them when it's cheap to do so, but do not bend the design or add migration shims to keep old data alive. This applies to data only — don't break unrelated Onyx surfaces.
- **Keep the product name "Craft" but do not rename backend `build/` modules** in V1. The existing names are implementation details; a broad rename adds migration risk without product value.
- **The sandbox should never receive:** the full Onyx document corpus, raw admin secrets, long-lived user auth tokens, or approval-bypass tokens. It receives only a session-scoped Craft token, session uploads/library files, materialized skill bundles, OpenCode config, and proxy/trust configuration.
- **Approval enforcement must live in Onyx-controlled paths** (proxy + backend orchestration). Agent prompts and OpenCode tool permissions are guidance, not the approval boundary.
- **Repo conventions to follow throughout:**
  - Raise `OnyxError` (not `HTTPException`); typed FastAPI returns (no `response_model=`).
  - All DB ops under `backend/onyx/db` or `backend/ee/onyx/db`.
  - All Celery tasks use `@shared_task` and every enqueue includes `expires=`. Existing direct sandbox file-sync enqueues should be removed or given expirations as part of search/sandbox work.
  - Implement timeout logic in task bodies — Celery's time limits don't work with thread pools.
  - Restart Celery workers after task changes (no auto-reload).
- **Remove the legacy `files/` corpus directory and demo-data path** as part of search/control-plane work. Any sandbox instructions or code paths still referencing them are stale.
- **Settled cross-project decisions:**
  1. Docker sandbox backend uses direct Docker control, not a separate runner service.
  2. Onyx search is exposed to OpenCode as a purpose-built HTTP tool that mirrors the regular Onyx search tool exactly.
  3. Every scheduled run creates a brand-new Craft session.
  4. Slack DM delivery is available only through a skill, not a custom Craft integration.
  5. Built-in skills are seeded into the DB so built-in and custom share one admin/selection path.
  6. Non-secret internet access defaults to pass-through.
  7. Approval enforcement lives in Onyx-controlled backend/proxy paths; review/notifications live in the Craft app.
