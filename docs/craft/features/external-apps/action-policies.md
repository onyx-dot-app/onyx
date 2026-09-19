# External-App Action Policies — Plan

> **Relationship to Approvals.** This plan owns the **policy layer** for
> external apps: the per-action catalog, the admin-set `ALWAYS | ASK | DENY`
> decisions, their storage, and the request→decision resolver. It is the
> external-apps-scoped policy layer for the
> [Craft egress proxy and approvals runtime](../egress-proxy-and-approvals/README.md).
> **Enforcement** (intercepting the request, holding it, prompting the user)
> lives in the egress proxy.
> This document defines the contract that proxy reads; it does not build the
> proxy.

## Summary

A connected external app currently grants the agent its entire capability
surface — all of Slack, all of Linear, etc. This plan lets an admin govern that
at the level of individual **actions**: for each action a built-in app can take,
choose `ALWAYS` (auto-approve), `ASK` (require approval), or `DENY` (block).
Custom apps get a single blanket policy in v0. Policies are persisted on the
admin-level `ExternalApp` and exposed through a transport-agnostic read contract
the egress proxy consumes to decide each outbound request.

The design rests on one separation: **recognition** ("what action is this
request?") is decoupled from **decision** ("what do we do about it?"), bridged by
a stable `action_id`. Recognition for built-ins lives in code next to the
provider; decisions live in the DB. That split is what makes the system both
extensible (adding a provider is a code-only change) and safe-by-default
(unrecognized requests fall to a fail-closed default).

---

## Problem

- A connected app is all-or-nothing. An admin cannot say "reads are fine, writes
  need approval, deletes are forbidden."
- The discriminating signal for "which action" is not uniform: REST encodes it in
  method + path, GraphQL encodes it in the request body (every call is
  `POST /graphql`). Endpoint-URL matching alone cannot tell a Linear issue *read*
  from an issue *delete*.
- Enforcement must be agnostic to *how* the agent issued the request (typed
  helper, raw `call` escape hatch, anything else), so classification can only
  rely on the request itself.
- The egress proxy must be able to **read** the resulting rules, but its runtime
  and delivery model are not yet decided — the contract must not bake either in.

---

## Goals & Requirements

### Functional

1. **Built-in per-action policy.** For each built-in app, an admin sees the
   app's catalog of logical actions and sets `ALWAYS | ASK | DENY` per action.
2. **Deterministic request→policy.** Any outbound request resolves to exactly one
   decision, regardless of how the agent issued it.
3. **Custom blanket policy (v0).** When an admin connects a custom app, they pick
   a single `ALWAYS | ASK` policy covering every request to that app.
4. **Sensible, overridable defaults.** Actions an admin hasn't configured resolve
   to a recommended default; unrecognized requests fall to a per-app default.
5. **Proxy-readable.** The persisted policy is exposed to the egress proxy via a
   stable read contract.

### Non-functional

- **Recognition is decoupled from decision.** The `action_id` string is the only
  interface between "what is this request" and "what do we do." Recognition logic
  never imports the policy enum; policy storage never imports request shapes.
- **Adding a provider is a code-only change** — no migration, no API change, no
  per-provider frontend work.
- **Safe by default.** A request that matches a built-in app but no catalog action
  fails closed; the system gets *more* semantic over time without becoming less
  safe.
- **Forward-compatible to custom per-endpoint rules and per-user overrides**
  without a schema rewrite.

### Out of Scope

- The egress proxy's request interception/forwarding
  ([runtime reference](../egress-proxy-and-approvals/README.md#request-lifecycle)).
- The `ASK` approval UX — event shape, hold mechanism, "remember for session",
  timeout (the Approvals workstream).
- Audit logging; per-user policy overrides; proxy-side caching.
- Per-endpoint policy for *custom* apps (the schema reserves space; see
  [Custom Apps](#custom-apps-v0--forward-path)).
- `DENY`-driven bundle filtering of `SKILL.md` (optional defense-in-depth,
  deferrable to enforcement).

---

## Architecture

### The core separation

Two questions, joined only by the `action_id`:

| | Question | Where it lives |
|---|---|---|
| **Recognition** | "What action is this request?" → `action_id` | Built-in: **code** (matchers on the provider). Custom: **data** (or nothing in v0). |
| **Decision** | "What do we do?" → `ALWAYS \| ASK \| DENY` | Always the **DB**, keyed by `action_id`. |

This is what lets built-in recognition be maintained Python and custom
recognition be admin-authored data, with no change to how decisions are stored
or resolved.

### Recognition pipeline (request → action_id)

Shared, provider-agnostic infrastructure (lives under `backend/onyx/external_apps/`;
a prototype informing these shapes was built in scratch as `request_action_parser.py`):

1. **Normalize** the request to secret-scrubbed facts:
   `{method, host, path, query, body_type, headers}` — Authorization reduced to
   `{present, scheme}`, never raw tokens/cookies.
2. **Parse the GraphQL body** when present (operation type + root fields) — the
   action is in the body, so `/graphql` alone is insufficient.
3. **Extract action(s)** via the provider's matcher, with a **layered fallback**
   so there is always at least one action (never a silent hole):

   ```
   semantic (slack.channel.read)  →  generic service (slack.http.post)  →  generic http (unknown.http.post)
   ```

   `action_id`s are hierarchical `service.resource.verb`; each carries a `risk`
   (`read | write | delete`), inferred from method (REST) or operation-type +
   destructive keyword (GraphQL).

### Resolution (request → decision), identical for built-in and custom

1. **App match** — request URL vs each enabled app's `upstream_url_patterns`
   (the existing seam). Multiple matches = misconfiguration; resolve
   deterministically (most-specific / lowest id) or fail closed.
2. **Normalize** (+ parse GraphQL body).
3. **Extract action(s)** — built-in: provider matcher → `action_id`(s);
   custom v0: nothing fires.
4. **Resolve each action**:
   `policy = override_row ?? catalog.default_state ?? app.default_policy`.
   Built-in off-catalog requests *and* all custom requests land on
   `default_policy`.
5. **Combine** — most restrictive wins: **`DENY > ASK > ALWAYS`**
   (order-independent; admins never manage rule ordering).

### Where it plugs in (code that exists today)

The [providers refactor](../../../../backend/onyx/external_apps/providers/base.py)
already established the contract: every provider declares a `spec: ProviderSpec`
(`ExternalAppProvider`), and the OAuth subset adds the flow
(`OAuthExternalAppProvider` / `OAuthProviderSpec`). The catalog + matcher attach
to the **base** `ProviderSpec` / `ExternalAppProvider`, because policy applies to
every provider regardless of how it authenticates. The admin UI is already
descriptor-driven via `BuiltInExternalAppDescriptor` (`_descriptor_for` in
`providers/__init__.py`), so catalog fields flow to the frontend with no
per-provider FE work.

---

## Data Model

### `external_app_policy` (new table) — the decision, sparse (overrides only)

| Column | Notes |
|---|---|
| `id` | surrogate PK |
| `external_app_id` | FK → `external_app(id)` ON DELETE CASCADE |
| `action_id` | `text` — hierarchical `service.resource.verb` (built-in: a catalog id; reserved for custom per-endpoint ids later) |
| `policy` | `text NOT NULL CHECK (policy IN ('ALWAYS','ASK','DENY'))` — Onyx convention: string + CHECK, not a PG enum |
| `name` | `text NULL` — NULL for built-in (display comes from the code catalog at read time); set for custom |
| `description` | `text NULL` — same |
| `match` | `jsonb NULL` — reserved: NULL in v0 (built-in matchers live in code; custom is blanket-only). Populated when per-endpoint custom rules land. |
| `created_at`, `updated_at` | `timestamptz` |
| UNIQUE | `(external_app_id, action_id)` |

Sparse on purpose: only admin **overrides** are stored. Unset built-in actions
resolve to the catalog `default_state` at read time, so new catalog entries
auto-apply their default to existing apps with **no backfill**.

### `external_app.default_policy` (new column) — fallback + custom blanket policy

- `text NOT NULL CHECK (policy IN ('ALWAYS','ASK','DENY'))`.
- **Built-in seed: `DENY`** — off-catalog requests fail closed (we own the
  catalog, so off-script is suspicious).
- **Custom seed: admin-chosen `ALWAYS` or `ASK`** — applies to every request,
  because no matcher fires for a custom app in v0.

One column does double duty: the built-in off-catalog fallback *and* the entire
custom-app policy. Both kinds share one resolution path.

---

## Built-in Catalog & Matchers (code)

Each provider declares `endpoint_catalog: list[EndpointSpec]` on its
`ProviderSpec`. An `EndpointSpec` binds id ↔ display ↔ recognition ↔ default:

- `id` (e.g. `slack.channel.read`), `normalised_name`, `description`,
  `risk` (`read | write | delete`), `default_state` (`ALWAYS | ASK | DENY`),
  `aliases: list[str]` (rename forward-compat), and `matches: list[MatchRule]`.

`MatchRule` is a small closed union (same shape in code and, later, in the custom
`match` jsonb):

- `RestRoute` — `method`, `path_regex`, optional resource type + capture.
- `GraphQLOp` — `operation_type`, root `field`, optional resource type.

Recommended defaults: reads → `ALWAYS`, writes → `ASK`, destructive
(`delete_event`, `chat.delete`, `issueArchive`, …) → `DENY`. All admin-overridable.

Matcher strategy per current provider: Slack → `/api/<method>`; Google Calendar
→ HTTP method + path regex; Linear → GraphQL root field / `operationName`.

---

## Custom Apps (v0 + forward path)

- **v0:** no catalog, no matchers. The app's `upstream_url_patterns` already
  answer "is this request this app?"; `default_policy` answers "what to do." The
  blanket policy *is* `default_policy` — zero policy rows needed, and the admin UI
  is a single dropdown.
- **Forward:** per-endpoint custom rules become `external_app_policy` rows with an
  inline `match` jsonb (the same `MatchRule` union). They produce `action_id`s
  that override `default_policy` — identical resolution path, no rework.

---

## Proxy Read Contract (transport-agnostic)

The proxy runtime (in-process Python vs separate service) and delivery model
(resolve-per-request vs pull-and-cache) are undecided, so the contract is defined
as pure functions and wrapping either behind an authenticated internal endpoint
is a deferred no-op:

- **Per-request:** `resolve_decision(app, normalized_request) -> Decision`
  (resolution steps 3–5).
- **Bulk:** `get_egress_ruleset(db) -> [per enabled app: {app_id, app_type,
  upstream_url_patterns, default_policy, actions: [{action_id, policy,
  match_spec}]}]`. Built-in matchers are **serialized** to the same shape as a
  custom `match`, so the proxy's view is uniform regardless of where a rule was
  authored.

The proxy needs **both** inputs joined by `action_id`: the matchers (→ produce
the id) and the policy rows + `default_policy` (→ the decision). Loading the
matchers alone is insufficient.

---

## Design Pitfalls (call out explicitly)

- **Match the request, not the wrapper.** The raw `call` escape hatch means
  recognition keys off the normalized request, never a wrapper subcommand. The
  catalog must be exhaustive enough that off-script calls fall to
  `default_policy`.
- **Orphan / unknown ids.** Reject unknown `action_id`s on the upsert write path;
  silently drop ids no longer in the catalog on read.
- **Display drift.** Keep `name`/`description` NULL for built-in rows; never copy
  catalog text into the DB.
- **State enum churn.** `ALWAYS | ASK | DENY` is the contract; a fourth state is a
  deliberate schema change.
- **GraphQL needs the body at the proxy.** REST decisions need only method+path;
  GraphQL requires the buffered, parsed body — a real constraint on the proxy.

---

## Implementation Phases

1. **Catalog + matcher primitives (code).** In `providers/base.py`: add
   `EndpointPolicy` and `Risk` enums, the frozen `EndpointSpec`, the `MatchRule`
   union, `endpoint_catalog` on `ProviderSpec` (default `[]`), and
   `extract_actions(normalized_request) -> list[Action]` on `ExternalAppProvider`
   (base default returns the generic fallback).
2. **Shared recognition infra (code).** Normalizer + GraphQL parser + generic
   fallback/risk helpers under `backend/onyx/external_apps/` (port the prototype;
   prefer `graphql-core`'s parser over the brace-walker for production).
3. **Per-provider catalogs + matchers.** ~6–12 `EndpointSpec`s each in the three
   provider files, with `MatchRule`s and recommended `default_state`s.
4. **DB schema (hand-written migration).** `external_app_policy` table +
   `external_app.default_policy` column; `ExternalAppPolicy` model +
   `default_policy` field in `db/models.py` (relationship
   `cascade="all, delete-orphan"`); seed `default_policy` in `create_external_app`
   (built-in `DENY`; custom from the request).
5. **DB helpers (`db/external_app.py`).** `get_policies` / `replace_policies`
   (full-replace in one commit) / `set_default_policy`, and the resolver
   functions `resolve_decision` / `get_egress_ruleset`.
6. **Admin API.** Extend `BuiltInExternalAppDescriptor` with
   `actions: [{action_id, normalised_name, description, risk, default_state}]`
   (`CUSTOM`/empty → `[]`); extend `UpsertExternalAppRequest` with
   `action_policies` + `default_policy`; extend `ExternalAppAdminResponse` with
   the merged view + `default_policy`. On upsert: validate keys against the
   catalog (canonicalise aliases), reject unknowns, then `replace_policies`.
7. **Frontend (`ConfigureProviderModal.tsx`).** Built-in → `descriptor.actions`
   grouped by resource, a 3-state control per action initialised from the merged
   state, risk presets ("all reads → Allow"), and a "default for unrecognized
   requests" control bound to `default_policy`. Custom → a single `default_policy`
   dropdown. Opal components per `web/AGENTS.md`; admin-only.

---

## Open Decisions

- **Off-catalog default for built-in: fail-closed vs fail-to-ask.** Plan seeds
  `DENY` (we own the catalog). The Approvals proposal leans `ASK` for genuinely
  unknown services; reconciled here by reserving the graded-`ASK` default for the
  *custom* tier.
- **Custom v0 surface: dropdown only, or `approvals.json` too?** Plan ships the
  single-dropdown blanket policy; a bundle-uploaded `approvals.json` for
  per-endpoint custom rules is deferred to the forward path.
- **Proxy runtime + delivery model** (resolve-per-request vs pull-and-cache) —
  owned by the egress/Approvals workstream; the read contract supports both.

---

## Tests

Primary: one focused **external-dependency-unit** file (DB + API), plus **unit**
tests for the pure normalizer/matchers/resolver.

- **Upsert round-trip** — `action_policies` + `default_policy` persist and return
  in the merged view.
- **Validation** — unknown `action_id` rejected; alias canonicalised; invalid
  policy value rejected.
- **Merge-on-read** — partial overrides return catalog `default_state` for unset
  actions; orphan id (in DB, gone from catalog) silently dropped.
- **Descriptor** — `/admin/apps/built-in/options` includes a stable catalog per
  built-in; `CUSTOM` → `actions: []`.
- **Resolver / matchers (unit, no services)** — per provider, representative
  requests (including a raw-`call`-style off-catalog request and a GraphQL batch)
  extract the expected `action_id`s and resolve to the expected decision, honouring
  override > catalog default > `default_policy` and `DENY > ASK > ALWAYS`; a custom
  app with only `default_policy` returns the blanket decision for any request.
- **Normalizer (unit)** — secrets scrubbed; REST vs GraphQL `body_type` detection;
  GraphQL operation/field extraction incl. batch and unparseable-fails-loud.

No integration / Playwright until the proxy enforcement workstream lands — there
is no end-to-end egress behaviour to assert yet. The schema + resolver is a data
contract; per the repo's "don't overtest" guidance, the focused DB-test file plus
pure unit tests cover it.

---

## Future Work

- Per-endpoint **custom** rules via the reserved `match` jsonb column.
- **Per-user** policy overrides (a sibling table; the org-level shape stays
  unchanged).
- `DENY`-driven **bundle filtering** so denied actions are omitted from the
  delivered `SKILL.md`/wrapper (defense in depth atop the authoritative proxy).
- **Audit** of every decision, once enforcement lands (see the Approvals plan).
