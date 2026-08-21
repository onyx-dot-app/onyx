# UI Capability Model — Server-Driven Affordance Gating for Scoped Group Permissions

Status: design (v2, revised after adversarial pressure test) · Task: group-manager-scoped-permissions · Supersedes: 06-frontend-affordance-followups.md · Layer: UI/read-projection + a small behavior-preserving backend refactor (PR1-5 enforcement behavior unchanged)

> **⚠️ Read with D8/D9 ([00-index](00-index.md)) in hand.** Every mention below of **agent-mediated** tool/MCP
> scope — `agent_mediated_scope_allows`, `get_action_agent_scope`, `get_mcp_server_agent_scope`, and the
> `M|O` classification of action/MCP **edit** — describes a model that was built and then **dropped**.
> Action and MCP-server management is now plain **owner-or-admin** (`can_manage_own_tool` /
> `_ensure_mcp_server_owner_or_admin`), and the shipped projection matches: `tool_permissions` /
> `mcp_server_permissions` take a single `can_manage` bool. Agent-derived scope survives only for *viewing*
> an MCP server connected to a managed group. Everything else in this document still applies.

## Changelog vs v1

1. **Shared decision helper (by-construction) — D1.** The projection stamps each tag by calling the *same* `can_<action>` boolean the write guard (`assert_*`) calls, so `project == enforce` holds by construction, not by discipline (§2.3, §3.1a).
2. **Per-action predicates — D2.** Each action's tag is stamped by *its own* real gate (M / A / O / M|O / O|A), replacing the wrong "one filter per resource" that mis-stamped ≥3 actions per resource (§3.3, §5).
3. **Hot-path / N+1 — D3.** Never stamp the chat/explore list; per-card tags ride the per-card fetch the card already makes; list callers preload the editable + managed sets once via a `ctx` so per-row stamping does no DB (§3.2, §4.4).
4. **Drop codegen + required field — D4.** Hand-write the 7 per-resource action unions, make `permissions` a *required* (non-optional) field, and add a route-coverage test — no codegen pipeline (§4.5, §6.1).
5. **Per-page default-deny — D5.** The SSR admin gate default-denies un-enumerated `/admin/*` paths instead of failing open (§3.5, §4.3).
6. **Federated admin-only — D6.** Federated connectors have no scope model → gate on `isAdmin`, enumerate `/admin/federated` as FULL_ADMIN (§5.6).
7. **Revert keeps Make-Manager — D7.** The PR6-v1 revert keeps the Make/Revoke Manager toggle — the only UI that reaches PR5's assign-manager route (§6.4).
8. **Cached-vs-live invalidation — D8.** Every manager-status change — including external group-sync, not just the manual toggle — recomputes perms server-side and busts `['me']` (§3.4, §6.3).

## Table of Contents

- [1. Overview & Motivation](#1-overview--motivation)
  - [1.1 Evidence](#11-evidence)
  - [1.2 Three structural root causes](#12-three-structural-root-causes)
  - [1.3 Goals](#13-goals)
  - [1.4 Non-Goals](#14-non-goals)
  - [1.5 Relation to PR1–6 & doc 06](#15-relation-to-pr16--doc-06)
- [2. Architecture (High-Level Design)](#2-architecture-high-level-design)
  - [2.1 Two-layer gate model](#21-two-layer-gate-model)
  - [2.2 The three fields](#22-the-three-fields)
  - [2.3 Shared-helper invariant (one `can_*`, three callers)](#23-shared-helper-invariant-one-can_-three-callers)
  - [2.4 Before / after (one affordance)](#24-before--after-one-affordance-edit-this-agent-on-a-chat-card)
  - [2.5 Why it stays scalable](#25-why-it-stays-scalable)
  - [2.6 Industry grounding](#26-industry-grounding)
- [3. Backend Design](#3-backend-design)
  - [3.1 One shared decision helper (PDP → PEP + projection + test)](#31-one-shared-decision-helper-pdp--pep--projection--test)
  - [3.1a D1 — One Shared Decision Helper (`can_*`), guard-by-guard](#31a-d1--one-shared-decision-helper-can_-guard-by-guard)
  - [3.2 Read-side projection: `permissions_for` + ctx (no N+1)](#32-read-side-projection-permissions_for--ctx-no-n1)
  - [3.3 Per-action predicate table](#33-per-action-predicate-table--each-actions-tag-comes-from-its-own-real-gate)
  - [3.4 `/me.admin_capabilities` — server-computed Layer-1 set (+ cache coherence)](#34-meadmin_capabilities--server-computed-layer-1-set--cache-coherence)
  - [3.5 Per-page access gate (AdminSSChrome SEAM) — default-deny](#35-per-page-access-gate-adminsschrome-seam--default-deny)
  - [3.6 `POST /capabilities` batch endpoint — deferred](#36-post-capabilities-batch-endpoint--deferred)
  - [3.7 Connectors is the reference implementation](#37-connectors-is-the-reference-implementation--but-does-not-generalize-to-toolmcp)
- [4. Frontend Design](#4-frontend-design)
  - [4.1 The `<Can>` primitive (Layer 2)](#41-the-can-primitive-layer-2)
  - [4.2 `useUser()` new shape](#42-useuser-new-shape)
  - [4.3 Coarse consumption (Layer 1)](#43-coarse-consumption-layer-1)
  - [4.4 Per-item consumption — collapse the duplication](#44-per-item-consumption--collapse-the-duplication)
  - [4.5 Hand-written per-resource action unions (no codegen in v1)](#45-hand-written-per-resource-action-unions-no-codegen-in-v1)
  - [4.6 Deletions](#46-deletions)
- [5. Affordance → Action Mapping (complete)](#5-affordance--action-mapping-complete)
  - [5.1 Agents / Personas — 18](#51-agents--personas--18-dto-map-editm-deleteoa-sharem-featurea-publishoa-lista-reordera-view_statso)
  - [5.2 Actions / MCP — 9](#52-actions--mcp--9-mcp-mcpserver-editmo-deleteo-authenticateo-manage_statuso-openapi-toolsnapshot-editmo-deletea-togglea)
  - [5.3 Skills — 8](#53-skills--8-customskillresponse-editm-deletea-manage_accessm-publisha)
  - [5.4 Groups — 6](#54-groups--6-usergroup-managem-per-group-deletea-edit_permissionsa-edit_token_limitsa)
  - [5.5 Doc sets — 3](#55-doc-sets--3-documentsetsummary-editm-deletea-manage_accessm-publisha)
  - [5.6 Connectors (cc_pair) — 3](#56-connectors-cc_pair--3-the-good-domain-is_editable_for_current_user-already-ships--the-template)
  - [5.7 Nav / page access — 2](#57-nav--page-access--2)
- [6. Testing, Rollout & PR Roadmap](#6-testing-rollout--pr-roadmap)
  - [6.1 Contract test — project == enforce](#61-contract-test--project--enforce-the-anti-drift-guarantee)
  - [6.2 Security note — flags are affordance-only](#62-security-note--flags-are-affordance-only)
  - [6.3 Cache hygiene (React Query)](#63-cache-hygiene-react-query--incl-cached-vs-live-manager-status-d8)
  - [6.4 Rollout](#64-rollout)
  - [6.5 PR roadmap](#65-pr-roadmap-5-review-sized-prs-drift-checkpoint-each)
  - [6.6 Open decisions](#66-open-decisions)

---

## 1. Overview & Motivation

Onyx's group-manager feature lets a non-admin manage resources *within the groups they manage*. The backend enforcement for this (PR1–PR5) is built, vetted, and fail-closed — it is the real security boundary. The **UI**, however, guesses at that boundary from a second, client-side re-derivation of policy that has already drifted out of agreement with the server. The result is not a security hole; it is an **affordance-correctness** problem: buttons that shouldn't render do, buttons that should render don't, and clicks that pass the client gate 403 at the server. A ground-truth inventory of every permission-gated affordance in the web app quantifies the drift.

### 1.1 Evidence

An 8-agent inventory audited 109 permission-gated UI affordances against the real backend predicate. **49 (45%) are mis-gated.**

| Domain | Mis-gated | Total | Rate | Notes |
|---|---:|---:|---:|---|
| Agents / Personas | 18 | 23 | 78% | worst cluster; 4× `canUpdateFeaturedStatus` fork (below) |
| Actions / MCP / OpenAPI | 9 | 19 | 47% | mixes owner-only + scoped + admin in one surface |
| Skills | 8 | 11 | 73% | no per-item signal at all |
| User Groups | 6 | 17 | 35% | missing per-group `manage` signal |
| Document Sets | 3 | 9 | 33% | page double-fetches + set-diffs to fake editability |
| Connectors (cc_pair) | 3 | 18 | 17% | **the good domain** — already ships `is_editable_for_current_user` |
| Navigation | 2 | 12 | 17% | coarse-only |
| **Total** | **49** | **109** | **45%** | |

Connectors scoring best is the tell: it is the one domain that already stamps a server-computed per-item flag (`backend/onyx/server/documents/connector.py:1231`, `cc_pair.py:323`). Everywhere the client is left to *infer* the boundary, it gets ~half the affordances wrong.

### 1.2 Three structural root causes

```
                     server truth (PDP: db/scoped_permissions.py)
                              │
          ┌───────────────────┴─── enforced correctly (GATE 2, PR1–5)
          │
   client RE-DERIVES it ──► drift ──► 49/109 wrong affordances
```

1. **The client re-derives policy.** `web/src/lib/permissions.ts:33` `visibilityPermissions()` blanket-injects all 6 `SCOPED_MANAGER_PERMISSIONS` into `useUser().permissions` with **zero group scoping** — a manager appears to hold `MANAGE_AGENTS` *everywhere*. This is a second, drifting source of truth for policy the server already owns.

2. **The manual 3-tier gate is un-followable.** To gate one action a dev must choose between injected `permissions`, raw `effective_permissions`, or `isAdmin` — and choose right every time. `canUpdateFeaturedStatus` exists in **four** copies; **three read the wrong tier**:

   | Copy | Reads | Verdict |
   |---|---|---|
   | `AgentRowActions.tsx:68` | `user.effective_permissions` | ✅ correct (managers excluded) |
   | `AgentCard.tsx:57` | injected `permissions` | ❌ manager sees Feature |
   | `ShareAgentModal.tsx:79` | injected `permissions` | ❌ |
   | `AgentEditorPage.tsx:492` | injected `permissions` | ❌ |

   Same feature, four sites, 3-of-4 wrong — because the tier choice is manual.

3. **The per-item signal doesn't exist**, so ownership stands in for editability. `checkUserOwnsAgent` (`web/src/lib/agents/utils.ts:10`) gates edit/share/delete on `agent.owner?.id === userId`. It is wrong in **both** directions: managers/editors who *can* edit but don't own → affordance hidden; rows that are readable-not-editable → affordance shown → **403 on click**.

### 1.3 Goals

- Make every permission-gated affordance agree with what the server enforces — **project == enforce by construction**: one shared `can_<action>` helper is called by the write guard, the read projection, and the contract test, so the projected tag and the enforced decision are literally the same boolean (§2.3) — not two implementations kept in sync by discipline.
- Collapse the 3-tier manual choice into two mechanical primitives: `useCapabilities([...])` (Layer 1) and `<Can resource action>` (Layer 2). No dev tier-picking.
- Delete the client-side policy re-derivation (`visibilityPermissions`); make the client a pure renderer of server-computed fields.
- Forward-compatible: server can add an action key to a resource's `permissions` map with **no client deploy** (fail-closed: missing key ⇒ `false`).

### 1.4 Non-Goals

- **Not changing what backend enforcement decides.** GATE 2 / the PR1–5 PEP remain the security boundary; every guard keeps its exact `OnyxErrorCode`, message, and trigger. A small **behavior-preserving** refactor *is* in scope — it lifts each guard's boolean decision into a shared `can_<action>` helper that the guard still calls before raising (§2.3), so the guards enforce identically. The **existing PR1–5 enforcement suite is the proof**: it must stay green with zero edits.
- **Not a security fix.** Enforcement is already fail-closed; a mis-gated button that 403s is a UX bug, not an escalation. This work is affordance-correctness + maintainability only.
- **The `can_<action>` helper is required, not deferred.** D1 promotes it from the old "optional `can()` facade" to a v1 core — but as an **internal server function**, not an HTTP endpoint. Only the *batched* `POST /capabilities` endpoint stays deferred (§3.6).

### 1.5 Relation to PR1–6 & doc 06

| PR | Scope | This doc |
|---|---|---|
| PR1–5 (`…perms-pr5-manager-assignment-membership`) | backend PDP + PEP, built & vetted | **untouched** — the source of truth we read from |
| PR6-v1 (on origin) | first UI pass | **reverted**; left on origin as reference |
| **PR6-v2** (`Subash-Mohan/perms-pr6-manager-ui-v2`, off PR5) | UI/read-projection redesign | **this doc**, ~4 review-sized PRs |

Doc `06-frontend-affordance-followups.md` first named the 3-tier model and the `is_editable` gap for agents. This document **supersedes and generalizes it**: the per-item flag becomes a uniform `resource.permissions: dict[str,bool]` across *all* seven domains, each entry stamped by the guard's own extracted `can_<action>` helper (§2.3), with the 3-tier choice removed rather than documented.

---

## 2. Architecture (High-Level Design)

The client stops deriving policy. The server emits two authoritative signals — a coarse capability set on `/me` and a per-item boolean map on every resource DTO — and the client becomes a pure renderer over them. The per-item map is stamped by a shared `can_<action>` helper that the **write guard also calls** (§2.3), and the coarse set by a server-side capability union — so neither can drift from what the backend enforces. (Backend mechanics are detailed in §3; client mechanics in §4.)

### 2.1 Two-layer gate model

Every affordance resolves to exactly one of two questions. Never a hand-rolled token bundle.

```
                 ┌──────────────────── SERVER (authoritative) ────────────────────┐
   GET /me ─────▶│  admin_capabilities = effective_permissions                    │
                 │                       ∪ (SCOPED_MANAGER_PERMISSIONS if manager) │
   GET /list ───▶│  DTO.permissions = { edit, delete, share, feature, ... }       │
   GET /detail ─▶│  (fail-closed boolean map, one per resource row)               │
                 └───────────────┬───────────────────────────┬────────────────────┘
                                 │                            │
                    LAYER 1 — COARSE               LAYER 2 — PER-ITEM
                 "can manage X somewhere"        "can I do A to THIS x"
                 nav link · page reach · New X    row button · menu item · modal action
                 useCapabilities(['agent:create'])  <Can resource={x} action="edit">
                   reads admin_capabilities           reads x.permissions["edit"]
```

- **Layer 1 (coarse)** answers *reach*: does a nav link show, does a page SSR-load, does the global "New X" button exist. Capability check — but re-sourced from server-computed `admin_capabilities`, not client-derived tokens. Managers included.
- **Layer 2 (per-item)** answers *authority on one resource*: read `resource.permissions[action]`. No token can express "…but only for this row"; the boolean map can. Missing key ⇒ `false`.

`is_admin` (`FULL_ADMIN_PANEL_ACCESS`) is retained only for affordances that are genuinely full-admin-only (e.g. reorder agents).

### 2.2 The three fields

The fix is refusing to overload one field. Three fields, three audiences, one of which is new-per-DTO.

| field | shape | who computes | consumed by | managers in it? |
|---|---|---|---|---|
| `effective_permissions` | `list[str]` (raw global tokens) | unchanged | backend middleware · org-wide gates (`isAdmin`, feature/publish/delete-global) | **No** — scoped manager power is deliberately absent |
| `admin_capabilities` | `list[str]` on `/me` (**NEW**) | server: `effective_permissions ∪ (SCOPED_MANAGER_PERMISSIONS if is_group_manager)` | **Layer 1 only** — nav/page/New-X reach; replaces `visibilityPermissions()` | **Yes** |
| `resource.permissions` | `dict[str,bool]` per DTO (**NEW**) | server: shared `can_<action>` helper, one per action (§2.3) | **Layer 2 only** — `<Can>` on that row | Per-item (a manager is `true` on in-scope rows, `false` elsewhere) |

Why `effective_permissions` and `admin_capabilities` must stay distinct: the union that lets a manager *reach* the Agents page (Layer 1) is exactly the thing that must **not** grant org-wide "feature this agent." Today `visibilityPermissions()` (`web/src/lib/permissions.ts:33`) injects the union into a single `permissions` field consumed by both, forcing devs to remember which of three tiers to read at each call site — and pick wrong (`canUpdateFeaturedStatus` is now copied to **four** sites: `AgentCard.tsx:57`, `ShareAgentModal.tsx:79`, `AgentEditorPage.tsx:492`, `AgentRowActions.tsx:68`). Splitting the field removes the choice.

### 2.3 Shared-helper invariant (one `can_*`, three callers)

Today each tricky guard **decides and raises in one body**; a read projection would have to **re-derive the same decision** separately — two implementations of one policy, guaranteed to drift. The fix makes drift impossible **by construction**: lift the *boolean decision* out of each guard into a shared helper `can_<action>(user, resource, db) -> bool`, then have all three consumers call it.

- **Guard (write, PEP — behavior unchanged):** `assert_<action>` now calls the helper, then raises its exact same `OnyxError` on `False`. Same code, same message, same trigger.
- **Projection (read, NEW):** stamps `dto.permissions[action] = can_<action>(user, res, db)`.
- **Contract test:** calls the *same* helper and asserts it equals "the guard did not raise."

```
              can_<action>(user, resource, db) -> bool      ◀── ONE decision, THREE callers
                     │
      ┌───────────────┼─────────────────────────┐
  assert_<action>   projection stamp          contract test
  calls helper,     dto.permissions[a] =      assert helper == (assert_ raised?)
  then RAISES       can_<action>(u,R,db)      across the actor × resource × action matrix
  (UNCHANGED)             │
      │             <Can action="edit"> renders ⇔ helper true
  403 if false
```

Because `assert_<action>` now *calls* `can_<action>`, "what the projection stamps" and "what the PEP enforces" are the **same boolean** — not a mirror that has to be kept faithful, but literally one function. The safety net proving enforcement is unchanged is the **existing PR1–5 enforcement suite**: it drives the `assert_*` guards and must stay green after the extraction. Green suite ⇒ the decision the PEP makes is provably identical; the only new thing is that the same decision is now also *readable*.

This is a small, behavior-preserving refactor across ~6 guards — `auth/scoped_permissions.py:55` (`assert_within_scope`), `:92` (`assert_manages_group`); persona `db/persona.py:340` + EE `ee/onyx/db/persona.py:73`; tool `tool/api.py:84`; mcp `mcp/api.py:1376`. Two of the underlying gates are **already booleans** (`user_can_view_assistant_stats` `ee/onyx/db/analytics.py:339`, `agent_mediated_scope_allows` `auth/scoped_permissions.py:36`) — the projection just calls them. Full per-guard extraction (Tier-0 scope booleans + Tier-1 read wrappers, and the write-shaped→read-mode adaptation) is specified in §3.1a.

> **Not "one filter per resource."** Each *action* bottoms out on its own real gate with its own shape — owner-bypass, creator-bypass, single-group membership, or a global token. The helper is `can_<action>`, not `can_touch_<resource>`; the editable filter `_add_user_filters(get_editable=True)` is a superset union that mis-stamps most actions if reused alone (over-reports scoped edits → 403; under-reports owner/creator affordances → their own button vanishes). See the per-action table in §3.3.

The connectors domain is the working proof that a server-computed per-item flag is enough for the client: `is_editable` / `is_editable_for_current_user` already ship on the cc_pair DTOs (`server/documents/connector.py:1231`, `cc_pair.py:324-326`) — effectively `can_edit` for a cc_pair. D1 generalizes that one flag into a `permissions` map whose every entry is stamped by the guard's own extracted helper.

### 2.4 Before / after (one affordance: "edit this agent" on a chat card)

Root cause #3 in miniature — ownership standing in for editability, wrong in **both** directions (a scoped manager who can edit but doesn't own → hidden; a readable-not-editable row → shown → 403 on click):

```tsx
// BEFORE — web/src/lib/agents/utils.ts:10 used as an edit GATE
{checkUserOwnsAgent(user, agent) && <EditAgentButton agent={agent} />}
```
```tsx
// AFTER — server already answered; client only renders
<Can resource={agent} action="edit">
  <EditAgentButton agent={agent} />
</Can>
// renders ⇔ agent.permissions.edit === true ; unknown/missing key ⇒ false
```

Same collapse applies to all tiers — one primitive replaces the three-way choice:

| old tier / signal | old call | new |
|---|---|---|
| coarse token | `hasPermission(permissions, MANAGE_AGENTS)` | `useCapabilities(['agent:create'])` (Layer 1) |
| org-wide token | `hasPermission(effective_permissions, MANAGE_AGENTS)` | `<Can resource={agent} action="feature">` (server returns `false` for managers) |
| ownership stand-in | `checkUserOwnsAgent(user, agent)` | `<Can resource={agent} action="edit">` |

`checkUserOwnsAgent` survives only as a **label** ("Your Agents"), never as a gate.

### 2.5 Why it stays scalable

| change | cost |
|---|---|
| new action on a resource (e.g. `"archive"`) | one server edit — extract/write its `can_archive` helper and add `archive` to that DTO's stamp loop. Clients not yet aware of the key render nothing (fail-closed), so **no client deploy is required** to ship the backend safely. |
| new resource | wrap its real gate(s) as `can_<action>` and stamp the map. No new policy — the guard already owns the decision. Cost varies by resource (see caveats below); it is **not** a uniform "copy the connectors filter." |
| policy change (scope rule) | edit the shared helper — `within_scope` / `manages_group`, or the per-resource `can_<action>` — **once**. Guard, projection, and contract test move together, or CI fails. |
| unknown/forward-compat keys | client `<Can>` treats missing key as `false`; old clients degrade safe, never over-expose. |

**Cost is not uniform — three honest caveats (see §3.2/§3.3):**

- **The hottest path stays untouched.** The chat/explore agent list is `MinimalPersonaSnapshot` fetched `get_editable=False` (`persona/api.py:501-517`) — do **not** stamp `edit`/`share`/`view_stats` onto it. Those per-card tags ride the per-card `GET /persona/{id}` (`FullPersonaSnapshot`) the card already fetches via `useAgent` (`AgentCard.tsx:64`) → **zero net-new query**. Never source them from the existing `user_permission`/`PersonaAccessLevel` field — it does **not** reflect scoped-manager edit rights (silent drift).
- **Admin lists (low traffic)** preload the editable-id set once and stamp each row from memory (the connectors template); the managed-group set rides on the `ctx` dataclass so per-row stamping does **no** DB.
- **Tools and MCP have no `get_editable` filter at all** — editability is agent-mediated per resource (`get_action_agent_scope` / `get_mcp_server_agent_scope`, one join each). The preload-once template does **not** transfer; stamp their `edit` tag via a batch resolver (`GROUP BY tool_id`/`server_id`, managed set hoisted once) or only on the detail/edit fetch — never row-by-row on the list.

The failure mode of the current design — *N* affordances × 3 tiers × hand-copied gates drifting independently (49/109 mis-gated) — is structurally removed: there is nothing left to hand-pick.

### 2.6 Industry grounding

The capability-on-the-DTO shape is standard: GitHub returns a `permissions` object per repo and exposes `viewerCanUpdate` / `viewerCanDelete` on GraphQL nodes — the server decides, the client renders. Batch/advisory capability probes (Google IAM `testIamPermissions`, OpenFGA `BatchCheck`, the AuthZEN advisory endpoint) inform UI only and are **never** the enforcement path — matching our split: `resource.permissions` and `admin_capabilities` gate *rendering*; GATE 2 remains the sole security boundary.

---

## 3. Backend Design

The write-side PEP already exists and is vetted (PR1–PR5) and is the security boundary — every mutating endpoint keeps its `require_permission(...)` dependency + its GATE-2 guard, byte-for-byte. What changes is *how the read projection agrees with it.* Rather than have the read side **re-derive** the same policy (a second implementation, guaranteed to drift), this redesign **extracts the boolean decision out of each guard into a shared helper** `can_<action>(user, resource, db) -> bool`. The guard keeps deciding-and-raising (it now calls the helper, then raises — behavior unchanged); the projection stamps the DTO tag by calling the **same** helper; the contract test calls the **same** helper. `project == enforce` becomes true **by construction**, not by discipline.

This promotes the previously-"deferred" `can()` idea (old §1.4 non-goal, old §6.6 open-decision) to a **required, core part of v1** — but as an *internal server function*, not an HTTP endpoint. The `POST /capabilities` HTTP facade stays deferred (§3.6).

### 3.1 One shared decision helper (PDP → PEP + projection + test)

There is no single SQL predicate that decides every action. Each action bottoms out on its **own** real gate — some are scope clauses (`assert_within_scope`), some are single-group membership (`assert_manages_group`), some are agent-mediated (`agent_mediated_scope_allows`), some are owner/creator-or-admin (`user_can_view_assistant_stats`, `_ensure_mcp_server_owner_or_admin`). The invariant is therefore *not* "one predicate, two call sites" — it is **one shared helper per action, called by three consumers**:

```
                 can_<action>(user, resource, db) -> bool     ◀── ONE decision, THREE callers
                       │
     ┌──────────────────┼───────────────────────┐
 assert_<action>   projection stamp        contract test
 (calls helper,    dto.permissions[a] =    assert helper == (assert_ raised?)
  then RAISES —    can_<action>(u,R,db)    over the 5×7 matrix
  UNCHANGED)              │
       │            <Can action="edit"> renders ⇔ helper true
   403 if false
```

The **safety net** that proves security is unchanged is the *existing* PR1–5 enforcement suite: it drives the `assert_*` guards and must stay green with **zero edits** after the refactor. If it stays green, the decision the PEP makes is provably identical — the only new thing is that the same decision is now *also readable* by the projection. (This replaces the old "read filter is a faithful mirror of GATE 2" framing, which was hand-wavy and — per §3.3 — wrong for most actions: the editable filter alone mis-stamps ≥3 of every resource's actions.)

### 3.1a D1 — One Shared Decision Helper (`can_*`), guard-by-guard

Two-tier helper layout. Tier 0 = generic scope booleans in `auth/scoped_permissions.py`; Tier 1 = per-resource read wrappers that resolve current state, then call Tier 0.

| Tier | Helper | File | Extracted from | Shape |
|---|---|---|---|---|
| **0 (generic scope booleans)** | `within_scope(...) -> bool` | `auth/scoped_permissions.py` | `assert_within_scope` (`:55`) | write-shaped (current/requested/non-public) |
| | `manages_group(...) -> bool` | `auth/scoped_permissions.py` | `assert_manages_group` (`:92`) | single-group |
| | `agent_mediated_scope_allows(...)` | `auth/scoped_permissions.py:36` | — **already a bool** | reuse as-is |
| **1 (per-resource read wrappers)** | `can_edit_persona` / `can_share_persona` | `db/persona.py`, `ee/onyx/db/persona.py` | `_assert_persona_update_within_managed_scope` (`:340`), `_assert_group_share_within_scope` (ee `:73`) | resolve current state → call Tier-0 |
| | `can_view_persona_stats` | `ee/onyx/db/analytics.py:339` | `user_can_view_assistant_stats` — **already a bool** | reuse as-is (O-class) |
| | `can_edit_custom_tool` | `server/features/tool/api.py` | `_get_editable_custom_tool` (`:84`) + `_assert_action_within_managed_scope` (`:62`) | admin∨creator∨scoped |
| | `can_edit_mcp_server` | `server/features/mcp/api.py` | `_ensure_mcp_server_editable` (`:1376`) | admin∨owner(email)∨scoped |
| | `can_manage_group` | `auth/scoped_permissions.py` | thin over `manages_group` | single-group |

Two guards need **no extraction** — they are already booleans (`agent_mediated_scope_allows` `:36`, `user_can_view_assistant_stats` `:339`); the projection just calls them. That is a bonus, not the norm.

#### Tier 0 — generic scope booleans (`auth/scoped_permissions.py`)

`assert_within_scope` (`:55-89`) → `within_scope` + thin raiser. The current guard fuses decide + raise:

```python
def assert_within_scope(user, db_session, *, permission, current_group_ids,
                        requested_group_ids, is_non_public) -> None:
    authority = has_permission(user, permission)
    if authority is PermissionAuthority.GLOBAL:
        return
    if authority is PermissionAuthority.SCOPED:
        managed = get_scoped_groups(user, db_session, permission)
        final = set(current_group_ids) | set(requested_group_ids)
        if managed and final and final.issubset(managed) and is_non_public:
            return
    raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Group managers can only ...")
```

Refactored — the decision is extracted; the raise is unchanged:

```python
def within_scope(user, db_session, *, permission, current_group_ids,
                 requested_group_ids, is_non_public,
                 managed_group_ids: set[int] | None = None) -> bool:
    """Pure GATE-2 decision. No raise. Called by assert_within_scope (write),
    the per-row read wrappers (projection), and the contract test.
    `managed_group_ids` lets a list caller pass a preloaded managed set so
    per-row stamping issues no DB query (§3.2); None re-queries (single-item/test)."""
    authority = has_permission(user, permission)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is PermissionAuthority.SCOPED:
        managed = (managed_group_ids if managed_group_ids is not None
                   else get_scoped_groups(user, db_session, permission))
        final = set(current_group_ids) | set(requested_group_ids)
        return bool(managed and final and final.issubset(managed) and is_non_public)
    return False

def assert_within_scope(user, db_session, *, permission, current_group_ids,
                        requested_group_ids, is_non_public) -> None:
    if not within_scope(user, db_session, permission=permission,
                        current_group_ids=current_group_ids,
                        requested_group_ids=requested_group_ids,
                        is_non_public=is_non_public):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Group managers can only act on private resources "
                        "within the groups they manage.")
```

Same message, same trigger — the PR1–5 suite is unaffected.

`assert_manages_group` (`:92-104`) → `manages_group` + thin raiser:

```python
def manages_group(user, db_session, *, group_id,
                  managed_group_ids: set[int] | None = None) -> bool:
    if has_global_permission(user, Permission.MANAGE_USER_GROUPS):
        return True
    managed = (managed_group_ids if managed_group_ids is not None
               else get_scoped_groups(user, db_session, Permission.MANAGE_USER_GROUPS))
    return group_id in managed

def assert_manages_group(user, db_session, *, group_id) -> None:
    if not manages_group(user, db_session, group_id=group_id):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Group managers can only act within the groups they manage.")
```

#### The write-shaped → read-mode adaptation (the crux of D1)

`within_scope` is **write-shaped**: it evaluates a *proposed mutation* (`current_group_ids`, `requested_group_ids`, `is_non_public`). A projection asks a different question — *"can this user edit R **as it stands right now**?"* — there is no proposed change. The per-resource read wrapper (Tier 1) is where that adaptation lives: it re-reads R's **current** state and passes **`requested := current`** and **`is_non_public := not R.is_public`**:

```
WRITE guard  →  within_scope(current=DB groups, requested=REQUEST.groups, non_public=proposed)
READ wrapper →  within_scope(current=DB groups, requested=DB groups,      non_public=R state)
                                                 └── same value ──┘
```

Because both bottom out on `within_scope`, `can_edit_persona(u,R,db)` and "`assert_within_scope` would not raise for R's current state" are the **same boolean by construction** — the contract test only pins the read-mode arg-supply, not the policy.

#### Tier 1 — per-resource read wrappers

**Persona edit / share** (`db/persona.py:340`, `ee/onyx/db/persona.py:73`). Per §3.3 (D2): the projection is **read-editable AND managed-scope** — never `_add_user_filters(get_editable=True)` alone (superset union → over-reports → 403). Extract the scope-boolean from each guard, then compose with editable-membership.

`_assert_persona_update_within_managed_scope` (`:340`) short-circuits non-SCOPED holders and personal (no-group) agents, resolves current groups/privacy in-txn, then delegates the raise to `assert_within_scope`. Extract its body to a bool:

```python
# db/persona.py
def persona_update_within_scope(user, db_session, *, persona_id,
                                requested_group_ids, requested_is_public,
                                managed_group_ids: set[int] | None = None) -> bool:
    if has_permission(user, Permission.MANAGE_AGENTS) is not PermissionAuthority.SCOPED:
        return True                              # not governed by the managed-scope gate
    current_group_ids, current_is_public = _read_persona_scope(persona_id, db_session)
    if not current_group_ids and not requested_group_ids:
        return True                              # personal (no-group) agent
    return within_scope(user, db_session, permission=Permission.MANAGE_AGENTS,
                        current_group_ids=current_group_ids,
                        requested_group_ids=requested_group_ids,
                        is_non_public=not current_is_public and not requested_is_public,
                        managed_group_ids=managed_group_ids)

def _assert_persona_update_within_managed_scope(persona_id, request, user, db_session) -> None:
    # keep the exact `requested_* := request.* if not None else current` resolution
    # the guard already does (db/persona.py:363-368); abbreviated here.
    if not persona_update_within_scope(user, db_session, persona_id=persona_id,
                                       requested_group_ids=_resolved_groups(request, ...),
                                       requested_is_public=_resolved_public(request, ...)):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Group managers can only ...")
```

Read wrapper (projection + contract test call this):

```python
def can_edit_persona(user, persona: Persona, db_session, *,
                     editable_ids: set[int], managed_group_ids: set[int] | None = None) -> bool:
    return persona.id in editable_ids and persona_update_within_scope(   # AND, per §3.3
        user, db_session, persona_id=persona.id,
        requested_group_ids=[g.id for g in persona.groups],   # requested := current
        requested_is_public=persona.is_public,
        managed_group_ids=managed_group_ids,
    )
```

`editable_ids` comes from the existing `_add_user_filters(get_editable=True)` (`db/persona.py:82`), preloaded once per list (§3.2). The **AND** is what keeps a non-manager member out (scope-guard `True` for non-SCOPED, but editable-membership `False`) and keeps an out-of-scope manager out (editable may be `True`, scope-guard `False`).

**Share** has the same shape over `_assert_group_share_within_scope` (ee `:73`, called `:161`, body ends in `assert_within_scope` at ee `:104`): extract `persona_group_share_within_scope(...) -> bool`, then `can_share_persona = editable-membership AND persona_group_share_within_scope(read-mode: requested := current groups, original_is_public := persona.is_public)`.

**Persona view_stats — reclassify M → O (already a bool).** Per §3.3, the real gate is **not** the editable filter — it is `user_can_view_assistant_stats` (`ee/onyx/db/analytics.py:339`), which returns `owner OR FULL_ADMIN`. No extraction:

```python
def can_view_persona_stats(user, persona, db_session) -> bool:
    return user_can_view_assistant_stats(db_session, user, persona.id)   # O-class
```

> **⚠️ SUPERSEDED by D8 (2026-08-03).** Custom-tool and MCP edit are now **owner-or-admin only** — the
> agent-mediated `scoped` term was dropped. The shipped projection matches: `tool_permissions` /
> `mcp_server_permissions` (`permission_projection.py`) take a single `can_manage` bool sourced from
> `can_manage_own_tool` / `can_manage_mcp_server` (owner-or-admin), so the tables below that reference
> `agent_mediated_scope_allows` / `get_action_agent_scope` describe the old model. Everything else here still applies.

**Custom tool edit — reclassify M → admin ∨ creator ∨ scoped** (`tool/api.py:84`). Stamping only the scoped term hides Edit from a plain **creator** on their own action (`tool.user_id == user.id`, `:100`). `_assert_action_within_managed_scope` (`:62`) just wraps `agent_mediated_scope_allows` — extract its bool, then extract the full disjunction:

```python
def _action_within_managed_scope(tool_id, db_session, user) -> bool:
    group_ids, has_public, has_ungrouped = get_action_agent_scope(tool_id, db_session)   # db/tools.py:141
    return agent_mediated_scope_allows(user, db_session, group_ids=group_ids,
                                       has_public_agent=has_public,
                                       has_ungrouped_private_agent=has_ungrouped)

def can_edit_custom_tool(user, tool: Tool, db_session) -> bool:
    if tool.in_code_tool_id is not None:
        return False                                                   # built-in
    if Permission.FULL_ADMIN_PANEL_ACCESS in get_effective_permissions(user):
        return True                                                    # admin
    if tool.user_id is not None and tool.user_id == user.id:
        return True                                                    # creator bypass (:100)
    if has_permission(user, Permission.MANAGE_ACTIONS) is PermissionAuthority.SCOPED:
        return _action_within_managed_scope(tool.id, db_session, user) # scoped
    return False
```

`_get_editable_custom_tool` keeps its **404** (missing) and **400** (built-in) `HTTPException` raises for precise messaging, then delegates the perms decision to `can_edit_custom_tool` (raising `INSUFFICIENT_PERMISSIONS`, "You can only modify actions that you created."). `ToolSnapshot` already ships `user_id`, so the projection has the creator datum.

**MCP server edit — reclassify M → admin ∨ owner(email) ∨ scoped** (`mcp/api.py:1376`). MCP ownership is **by email** (`server.owner == user.email`, `:1386`); the DTO ships `owner: str`. Stamping only the scoped term hides Edit from the owner:

```python
def can_edit_mcp_server(user, server: DbMCPServer, db_session) -> bool:
    if Permission.FULL_ADMIN_PANEL_ACCESS in get_effective_permissions(user):
        return True                                    # admin
    if server.owner == user.email:
        return True                                    # owner-by-EMAIL (:1386)
    if has_permission(user, Permission.MANAGE_ACTIONS) is PermissionAuthority.SCOPED:
        group_ids, has_public, has_ungrouped = get_mcp_server_agent_scope(server.id, db_session)  # db/tools.py:153
        return agent_mediated_scope_allows(user, db_session, group_ids=group_ids,
                                           has_public_agent=has_public,
                                           has_ungrouped_private_agent=has_ungrouped)
    return False

def _ensure_mcp_server_editable(server, user, db_session) -> None:
    if not can_edit_mcp_server(user, server, db_session):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Only the server owner or a manager of its groups can modify this MCP server.")
```

MCP `delete`/`authenticate`/`manage_status` stay **O** via `_ensure_mcp_server_owner_or_admin` (`:1358`) — extract a sibling `can_admin_mcp_server` the same way if those tags are stamped.

**User group manage — distinct single-group shape** (`user_group`):

```python
def can_manage_group(user, group: UserGroup, db_session, *,
                     managed_group_ids: set[int] | None = None) -> bool:
    return manages_group(user, db_session, group_id=group.id,
                         managed_group_ids=managed_group_ids)   # Tier-0
```

`assert_manages_group` (`:92`, called at `ee/.../user_group/api.py:191,333`, `ee/.../db/user_group.py:545`) already wraps `manages_group` after the extraction above. The `manager_ids` on the group snapshot is **not** the gate — the gate is managed-set membership OR global `MANAGE_USER_GROUPS`.

#### Guard-by-guard summary

| Guard (file:line) | Current shape | Extracted bool | `assert_*` after | Read wrapper (projection) |
|---|---|---|---|---|
| `assert_within_scope` (`auth/scoped_permissions.py:55`) | decide+raise | `within_scope` | calls bool, raises | (used by persona wrappers) |
| `assert_manages_group` (`:92`) | decide+raise | `manages_group` | calls bool, raises | `can_manage_group` |
| `_assert_persona_update_within_managed_scope` (`db/persona.py:340`) | resolve+delegate-raise | `persona_update_within_scope` | calls bool, raises | `can_edit_persona` = editable ∧ bool |
| `_assert_group_share_within_scope` (`ee/…/persona.py:73`) | resolve+delegate-raise | `persona_group_share_within_scope` | calls bool, raises | `can_share_persona` = editable ∧ bool |
| `_get_editable_custom_tool` + `_assert_action_within_managed_scope` (`tool/api.py:84,62`) | fetch+decide+raise | `can_edit_custom_tool`, `_action_within_managed_scope` | keep 404/400 raises, delegate perms | `can_edit_custom_tool` |
| `_ensure_mcp_server_editable` (`mcp/api.py:1376`) | decide+raise | `can_edit_mcp_server` | calls bool, raises | `can_edit_mcp_server` |
| `user_can_view_assistant_stats` (`ee/…/analytics.py:339`) | **already bool** | — | (its own callers) | `can_view_persona_stats` |
| `agent_mediated_scope_allows` (`auth/scoped_permissions.py:36`) | **already bool** | — | — | (composed by tool/mcp wrappers) |

#### Behavior-preservation invariant (for the reviewer)

- Every `assert_*` keeps its **exact `OnyxErrorCode` + message**; the extraction only relocates the boolean, so the **existing PR1–5 enforcement suite is the proof security is unchanged** — it must stay green with zero edits.
- If a contract-test cell fails, the bug is in the **read wrapper's composition** (forgot the `editable ∧` for persona; stamped only the scoped term for tool/mcp) — **never** a reason to relax a guard.
- Fail-closed by shape: every helper's terminal branch returns `False`; unknown authority, empty managed scope, and missing resource state all deny.

### 3.2 Read-side projection: `permissions_for` + ctx (no N+1)

New module `backend/onyx/auth/permission_projection.py`. The projection **never re-derives policy** — it calls the §3.1 `can_<action>` helpers. To keep list paths off the N+1 path, the caller preloads a small `ctx` **once** and threads it through every per-row helper call so per-row stamping issues **no** DB query.

```python
# auth/permission_projection.py
@dataclass
class ScopeCtx:
    is_admin: bool                    # has_global_permission(user, <resource perm>)
    editable_ids: set[int]            # 1 scoped query; resources that HAVE _add_user_filters(get_editable=True)
    managed_group_ids: set[int]       # 1 query: fetch_managed_group_ids(user, db)  ── D3: passed into helpers
                                      #          so within_scope/manages_group do NOT re-query per row

def build_persona_ctx(user, db_session) -> ScopeCtx:
    return ScopeCtx(
        is_admin=has_global_permission(user, Permission.MANAGE_AGENTS),
        editable_ids=fetch_editable_persona_ids(user, db_session),   # wraps db/persona.py:82
        managed_group_ids=fetch_managed_group_ids(user, db_session), # db/scoped_permissions.py:34
    )

def persona_permissions(user, persona, ctx: ScopeCtx) -> dict[str, bool]:
    return {
        "edit":       can_edit_persona(user, persona, db=None,        # pure: reads ctx, no DB
                                       editable_ids=ctx.editable_ids,
                                       managed_group_ids=ctx.managed_group_ids),
        "share":      can_share_persona(user, persona, db=None,
                                        editable_ids=ctx.editable_ids,
                                        managed_group_ids=ctx.managed_group_ids),
        "view_stats": ctx.is_admin or persona.user_id == user.id,    # O-class (analytics.py:339 shape)
        "delete":     ctx.is_admin or _owner_or_owner_group(persona, ctx),  # O|A, §3.3
        "feature":    ctx.is_admin,   # A
        "list":       ctx.is_admin,   # A
        "publish":    ctx.is_admin or _owner_or_owner_group(persona, ctx),  # O|A
        "reorder":    ctx.is_admin,   # A (FULL_ADMIN)
    }
```

> **Adding `managed_group_ids` to the ctx (D3) is the whole point:** without it, each row's `within_scope`/`manages_group` re-runs `get_scoped_groups` → `fetch_managed_group_ids` (one query per row = N+1). With it preloaded, per-row stamping is pure set math. `db=None` is legal in the read wrappers precisely because `managed_group_ids` short-circuits the only DB call `within_scope` makes.

**Where each map is stamped — hot-path honesty (D3).** *Not all lists should carry the map.*

| Surface | Stamp the map? | Why |
|---|---|---|
| **Chat/explore agent list** — `list_personas` (`persona/api.py:501-517`, `MinimalPersonaSnapshot`, `get_editable=False`) | **NO** | Hottest read path in the app. Do **not** stamp `edit`/`share`/`view_stats` here. |
| **Agent card** — `get_persona` (`persona/api.py:568`, `FullPersonaSnapshot`) | **YES** | `AgentCard` already fetches this per card via `useAgent` (`AgentCard.tsx:64`) → **zero net-new query**; stamp the per-card tags here. |
| **Admin agent list** — `list_personas_admin` (`persona/api.py:215`, low traffic) | **YES** | Preload `ctx` once, stamp each row from memory (connectors template, §3.7). |

**Never** source per-card tags from the existing `FullPersonaSnapshot.user_permission` / `PersonaAccessLevel`: `get_persona_access_level` (`db/persona_sharing.py:40`) is documented (`:48`) as feeding "the sharing UI, not the editable fetch" — it does **not** reflect scoped-manager edit rights, so reusing it silently drifts. Stamp from the `can_*` helper, always.

**Tools & MCP have no editable filter — the connectors template does NOT copy to them (D3).** There is no `_add_user_filters(get_editable=True)` for tools or MCP servers; editability is **agent-mediated per resource** (`get_action_agent_scope` / `get_mcp_server_agent_scope`, one join each). So `ctx.editable_ids` doesn't exist for them, and "preload-once, stamp from memory" does not apply. Two acceptable strategies — pick per surface:

```
TOOL / MCP list  ── choose one ──
  (a) BATCH RESOLVER: one GROUP BY tool_id / server_id join resolving all
      rows' agent-scope up front; hoist managed_group_ids once → stamp from memory.
  (b) DETAIL-ONLY (v1 lean): do NOT stamp `edit` on the list; stamp it only on
      the detail/edit fetch (single resource → one join, no N+1).
```

v1 leans **(b)** for tool/MCP lists (edit is a per-card affordance the detail fetch already loads); add the batch resolver only when a list surface must show the edit tag at scale.

**List path (resources that DO have an editable filter):**

```python
ctx = build_persona_ctx(user, db_session)          # editable set + managed set resolved ONCE
for dto in rows:
    dto.permissions = persona_permissions(user, dto, ctx)   # pure, no DB → no N+1
```

The DTO field is **required** (D4/§3.3): `permissions: dict[str, bool]`, never optional — a stamp site that forgets to fill it is a type error, not a silently-empty map. Individual *action keys* remain fail-closed (a key absent from the dict ⇒ `false` on the client), which is what preserves forward-compat.

### 3.3 Per-action predicate table — each action's tag comes from ITS OWN real gate

The old "one filter per resource" was wrong: within a single resource, different actions bottom out on **different gate functions with different shapes**. This is an **action-level** table (action → real gate fn → scope class), verified against `HEAD`.

**Scope legend:** `M` = scoped-manager true iff in-scope (admin also true) · `A` = global/admin token only (managers → false) · `O` = owner/creator-or-admin (managers → false unless they own it) · **`M|O`** = scoped **OR** owner/creator **OR** admin (owner-bypass) · **`O|A`** = owner-or-global (owner bypass, but **not** the scoped-manager path).

| Resource | Action | Real gate (fn + file:line) | Scope | Notes |
|---|---|---|---|---|
| **Persona** | edit | `_assert_persona_update_within_managed_scope` → `assert_within_scope` `db/persona.py:340` (route `persona/api.py:336`, `ADD_AGENTS` allow_scope) **AND** read-editable `_add_user_filters(get_editable=True)` `db/persona.py:82` | M | Both gates; NOT `get_editable` alone (superset union → over-reports → 403) |
| | share | `_assert_group_share_within_scope` → `assert_within_scope` **EE** `ee/onyx/db/persona.py:73` (called `:161`; route `persona/api.py:443`) **AND** read-editable | M | EE-only; `_assert_persona_update…` doesn't fire on a groups-unchanged share |
| | **view_stats** | `user_can_view_assistant_stats` `ee/onyx/db/analytics.py:339` (route `ee/…/analytics/api.py:220`) | **O** | **M→O**: `FULL_ADMIN OR persona.user_id==user.id`. NOT the editable filter |
| | **delete** | `get_persona_by_id(is_for_edit=True)` `db/persona.py:1426` via `mark_persona_as_deleted` (route `persona/api.py:487`, `ADD_AGENTS` **no** allow_scope) | **O\|A** | `global MANAGE_AGENTS OR owner(user_id) OR owner-group member` — excludes scoped-manager rels, so ≠ edit's `M` |
| | feature | route `persona/api.py:177` `MANAGE_AGENTS` **no** allow_scope | A | global token |
| | list (listed) | route `persona/api.py:143` `MANAGE_AGENTS` **no** allow_scope | A | global token |
| | **publish** (is_public) | `update_persona_public_status` `db/persona.py:560` (route `persona/api.py:158`, `ADD_AGENTS` no allow_scope) | **O\|A** | `global MANAGE_AGENTS OR owner OR owner-group member` — a plain owner CAN org-publish their own agent; not pure A |
| | reorder | route `persona/api.py:196` `FULL_ADMIN_PANEL_ACCESS` | A | FULL_ADMIN |
| **DocumentSet** | edit / manage_access | `assert_within_scope` `document_set/api.py:91` (route `:76`, `MANAGE_DOCUMENT_SETS` allow_scope) + read-editable `db/document_set.py:42` | M | |
| | delete | route `document_set/api.py:123` `MANAGE_DOCUMENT_SETS` **no** allow_scope | A | global token |
| | publish (make-public) | create/update `is_public` → `assert_within_scope(is_non_public=…)` blocks scoped → global | A | scoped mgr can't publish org-wide |
| **Skill** | edit | `assert_within_scope` `skill/api.py:258,:304` (routes `:233` patch, `:287` bundle, `MANAGE_SKILLS` allow_scope) | M | **No `get_editable` filter exists** — scope via managed-groups ∩ skill grants |
| | manage_access (grants) | `assert_within_scope` `skill/api.py:355` (route `:339` `PUT …/grants`) | M | |
| | delete | route `skill/api.py:378` `FULL_ADMIN_PANEL_ACCESS` | A | FULL_ADMIN |
| | publish (is_public) | create/patch `is_public` → `assert_within_scope(is_non_public)` blocks scoped → global `MANAGE_SKILLS` | A | |
| **MCP server** | **edit** | `_ensure_mcp_server_editable` `mcp/api.py:1376` | **M\|O** | `FULL_ADMIN OR server.owner==user.email OR scoped(agent-mediated)`. Owner by **EMAIL**; DTO ships `owner:str` |
| | delete / authenticate / manage_status | `_ensure_mcp_server_owner_or_admin` `mcp/api.py:1358` | **O** | `FULL_ADMIN OR owner==email` |
| **OpenAPI action** (Tool) | **edit** | `_get_editable_custom_tool` `tool/api.py:84` (route `:140`, `MANAGE_ACTIONS` allow_scope) | **M\|O** | `FULL_ADMIN OR tool.user_id==user.id (creator) OR scoped(_assert_action_within_managed_scope:62)` |
| | delete | route `tool/api.py:167` `MANAGE_ACTIONS` **no** allow_scope | A | global route; creator bypass unreachable → A |
| | toggle (status) | route `tool/api.py:194` `MANAGE_ACTIONS` **no** allow_scope | A | global token |
| **UserGroup** | **manage** (per-group) | `assert_manages_group` `auth/scoped_permissions.py:92` (patch `:216`→`ee/…/user_group.py:545`, add-users `:239`, rename `:191`, agents `:282`, set-manager `:333`) | **M** (per-group) | `group_id ∈ managed set OR global MANAGE_USER_GROUPS` — single-group, NOT the editable filter |
| | delete | route `user_group/api.py:262` `MANAGE_USER_GROUPS` **no** allow_scope | A | global token |
| | edit_permissions | route `user_group/api.py:133` `PUT …/permissions` `FULL_ADMIN` | A | FULL_ADMIN |
| | edit_token_limits | POST create `assert_within_scope` `token_rate_limits/api.py:74` (allow_scope) = M; per-row PUT/DELETE + `GET /user-groups` `FULL_ADMIN` `:32,:101` = A | M (create) / A (PUT/DELETE) | Split gate |
| **Connector** (cc_pair) — TEMPLATE | edit / delete / manage_access | `get_connector_credential_pair_from_id_for_user(get_editable=True)` → `is_editable_for_current_user` `cc_pair.py:324-326`; list `is_editable` `connector.py:1231,1443` | M | Already ships the per-item flag |
| | publish (make-public) | access-controls → global `MANAGE_CONNECTORS` | A | |

**Why "one filter per resource" was wrong (3 lines):**
1. Within one resource, actions bottom out on **different gate fns with different shapes** — persona alone spans `edit`=editable-filter+scoped-clause (M), `view_stats`=owner-or-admin (O), `feature/list`=global-token (A), `delete/publish`=owner-or-global (O|A). No single filter reproduces all four → a per-resource filter mis-stamps ≥3 of them.
2. `_add_user_filters(get_editable=True)` is a **superset union** that **over-reports** for scoped actions (shows `edit` where the scoped-clause `+ is_non_public` gate would 403) *and* **under-reports** for owner/creator actions (tool/mcp/persona owners bypass the scoped path by `user_id`/`email` — stamping only the scoped term hides their own button).
3. Three resources (skill, tool, mcp) have **no `get_editable` filter at all** — editability is `assert_within_scope` (skill) or agent-mediated joins (tool/mcp) — so "reuse the resource's editable filter" doesn't even exist for them.

**Stamp sites (serializers).** Add the **required** `permissions: dict[str, bool]` and stamp via §3.2: `FullPersonaSnapshot.from_model` (per-card `GET /persona/{id}`, **not** the `MinimalPersonaSnapshot` list) · `DocumentSetSummary` · `CustomSkillResponse` · `MCPServer`/`ToolSnapshot` builders (detail/edit fetch, or batch-resolver list) · the EE `UserGroup` snapshot · connectors' `_get_connector_indexing_status_lite` (generalize its lone `is_editable` into the map; keep `is_editable` until the client cuts over).

**Backend coverage test (D4) — closes the "add action, forget to register" hole.** A companion to §3.1's contract test: enumerate every mutating scoped route (`require_permission(..., allow_scope=True)` or a body-level `assert_*` guard) and assert each maps to a stamped action key that is present in the hand-written per-resource action list. A new guarded route with no stamped key fails CI, so the projection can't silently lose an affordance.

```py
# backend/tests/external_dependency_unit/auth/test_permission_projection_contract.py
CAN = {("persona","edit"): can_edit_persona, ("persona","share"): can_share_persona,
       ("persona","view_stats"): can_view_persona_stats, ("tool","edit"): can_edit_custom_tool,
       ("mcp_server","edit"): can_edit_mcp_server, ("user_group","manage"): can_manage_group, ...}

def test_helper_matches_guard(db_session, actor, resource_kind, action):
    u, r = make_actor(actor), make_resource(resource_kind)
    helper_says = CAN[(resource_kind, action)](u, r, db_session)   # projection's boolean
    raised = guard_raised(resource_kind, action, u, r, db_session) # drive the assert_* guard
    assert helper_says == (not raised)                             # project == enforce

def test_every_scoped_route_has_a_stamped_key():
    for route in mutating_scoped_routes():                         # allow_scope / assert_* sites
        assert route.action_key in HANDWRITTEN_ACTIONS[route.resource]   # no orphan gate
```

Because `assert_*` now *calls* the helper, `test_helper_matches_guard` is **structural**, not coincidental — a future edit to `within_scope`/`manages_group` moves both sides together or fails CI.

### 3.4 `/me.admin_capabilities` — server-computed Layer-1 set (+ cache coherence)

New field on `UserInfo` (`backend/onyx/server/manage/models.py:131`), derived, never persisted, never consulted by the PEP. `effective_permissions` stays **global-only, unchanged**. `admin_capabilities` is **query-free** — `is_group_manager` is a column and the bundle is a constant:

```python
# UserInfo.from_model — no DB
caps = set(effective_permissions or [])
if user.is_group_manager:                        # cached column
    caps |= SCOPED_MANAGER_PERMISSIONS_EXPANDED  # auth/permissions.py:263 (implied-expanded)
admin_capabilities = sorted(caps)
```

**Cached `is_group_manager` vs live scope — the coherence hazard (D8).** Layer-1 (`admin_capabilities`) reads the **cached** `is_group_manager` bool; Layer-2 (`resource.permissions`) and the PEP resolve **live** scope (`fetch_managed_group_ids`). If the cache drifts *stale-true* — the user was demoted but `is_group_manager` is still `true` — the nav link and page show, but **every** per-item helper resolves `false` (dead buttons). If it drifts *stale-false*, the manager can't even reach the page. Both are avoidable only by recompute-on-change:

> **Requirement:** every mutation that changes a user's manager status MUST `recompute_user_permissions(user)` **and** bust the `['me']` query — **including external group-sync** (a user gains/loses a managed group via IdP/SCIM sync), not just the manual Make/Revoke-Manager toggle. §6.3 currently lists only the manual toggle; the sync path is the one that silently drifts. Document the staleness window: between a sync-driven status change and the next `['me']` refetch, Layer-1 nav can disagree with Layer-2 per-item — the PEP stays correct throughout (it never reads the cache), so the worst case is cosmetic (a shown-but-dead or hidden-but-reachable page), never an escalation.

### 3.5 Per-page access gate (AdminSSChrome SEAM) — default-deny

Today `AdminSSChrome.tsx` calls only `requireAdminAuth()` — coarse "has *some* admin permission" admission (`requireAuth.ts:108`). There is **no per-page check**, so a manager can SSR-load a `FULL_ADMIN_PANEL_ACCESS` page. The naïve fix (look up `ADMIN_ROUTES[path]`, redirect if `requiredPermission ∉ admin_capabilities`) **fails OPEN**: any `/admin/*` path *not in* `ADMIN_ROUTES` (`systeminfo`, `groups2`, `federated/[id]`) matches nothing and admits everyone. The gate must **default-deny**:

```
match = ADMIN_ROUTES[path]                       (admin-routes.ts:92; entry.requiredPermission single Permission, :86)
if match is None:                                # UNMATCHED /admin/* — DEFAULT DENY
    required = FULL_ADMIN_PANEL_ACCESS           # managers redirected off unknown admin pages
else:
    required = match.requiredPermission
if required ∉ me.admin_capabilities → redirect(getFirstPermittedAdminRoute(caps))
```

Because a manager's bundle never contains `FULL_ADMIN_PANEL_ACCESS`, unknown pages and full-admin pages both redirect managers; manager-reachable pages (`MANAGE_CONNECTORS`, `MANAGE_AGENTS`, …) pass. **Enumerate the currently-missing pages in `ADMIN_ROUTES`** with their real `requiredPermission` so they gate precisely rather than via the default-deny fallback:

| Route | requiredPermission |
|---|---|
| `/admin/systeminfo` | `FULL_ADMIN_PANEL_ACCESS` |
| `/admin/groups2` | `MANAGE_USER_GROUPS` (or `FULL_ADMIN` if it's the settings variant) |
| `/admin/federated`, `/admin/federated/[id]` | `FULL_ADMIN_PANEL_ACCESS` (federated has no scope model — see §5.6 / D6) |

This SSR gate is **defense-in-depth / least-astonishment, not the security boundary** — the boundary remains each endpoint's `require_permission(...)` + its GATE-2 guard. A manager who somehow reaches a full-admin page still 403s on every mutating call; the gate exists so the client never renders a page whose every action would 403. `requireAdminAuth` is re-sourced from `admin_capabilities` (drop `visibilityPermissions`).

### 3.6 `POST /capabilities` batch endpoint — deferred

For "orphaned" global affordances (a global *New X* button whose token isn't cleanly a single `admin_capabilities` membership, or future batched per-item checks). `testIamPermissions`-shaped, advisory only — **never** an enforcement path:

```
POST /capabilities  { "permissions": ["connector:create", "agent:feature", ...] }
  -> { "permissions": ["connector:create"] }        # allowed subset (fail-closed on omission)
```

**v1 does not need this** — `useCapabilities(['connector:create'])` reads `admin_capabilities` directly. Kept as a deferred appendix; add only when a global affordance can't be expressed as bundle membership. (Note the distinction from §3.1a's `can_*`: those are *required* internal server functions consumed by the projection; this HTTP facade is the *optional* client-facing batch probe.)

### 3.7 Connectors is the reference implementation — but does NOT generalize to tool/MCP

The connectors domain already does the batch pattern: preload the editable set once (`get_connector_credential_pairs_for_user(..., get_editable=True)`), split editable/non-editable, stamp `is_editable` per row (`build_connector_indexing_status(cc_pair, is_editable)`, `connector.py:1229`; detail `is_editable_for_current_user`, `cc_pair.py:326`). This PR generalizes that single boolean into the `permissions` map and copies **preload-once / stamp-each-row** to the resources that **have an editable filter**: persona (admin list), document set, skill, user group.

**It does NOT copy to tools and MCP servers.** Neither has `_add_user_filters(get_editable=True)`; editability is agent-mediated per resource (`get_action_agent_scope` / `get_mcp_server_agent_scope`, `db/tools.py:141,153` — one join each). Copying "preload once" there is impossible; a naïve per-row stamp is N+1. Follow §3.2's D3 fix instead: **batch resolver** (`GROUP BY tool_id`/`server_id`, hoist `managed_group_ids` once) **or** stamp `edit` **only on the detail/edit fetch** (v1 lean). No new policy is written — only the missing per-item signal is surfaced, sourced from the §3.1a helper.

---

_Verified paths (HEAD):_ `backend/onyx/auth/scoped_permissions.py:36,55,92` · `backend/onyx/db/scoped_permissions.py:25,34,39` · `backend/onyx/db/persona.py:82,340,560,1426` · `backend/onyx/db/persona_sharing.py:40,48` · `backend/ee/onyx/db/persona.py:73,104,161` · `backend/onyx/server/features/persona/api.py:143,158,177,196,215,336,443,487,501,568` · `backend/onyx/server/features/tool/api.py:62,84,100,140,167,194` · `backend/onyx/server/features/mcp/api.py:1358,1376,1386` · `backend/onyx/db/tools.py:141,153` · `backend/ee/onyx/db/analytics.py:339` · `backend/onyx/server/features/document_set/api.py:76,91,123` · `backend/onyx/server/features/skill/api.py:233,258,287,304,339,355,378` · `backend/ee/onyx/server/user_group/api.py:133,191,216,239,262,282,333` · `backend/ee/onyx/db/user_group.py:545` · `backend/onyx/server/manage/models.py:131` · `backend/onyx/server/documents/connector.py:1229,1231,1443` · `backend/onyx/server/documents/cc_pair.py:324-326` · `web/src/lib/admin-routes.ts:86,92` · `web/src/lib/auth/requireAuth.ts:108` · `web/src/layouts/chromes/AdminSSChrome.tsx`.

---

## 4. Frontend Design

The client stops computing policy. Every gate resolves to reading a server field: a coarse token in `admin_capabilities` (Layer 1) or a boolean in `resource.permissions[action]` (Layer 2). `visibilityPermissions()` — the client-side re-derivation — is deleted. The complete per-affordance inventory these primitives replace is enumerated in §5.

```
                     ┌─────────────── /me ───────────────┐
 Layer 1 (coarse) ── │ admin_capabilities: string[]       │ ── nav / page-reach / "New X"
                     └────────────────────────────────────┘
                     ┌──────────── resource DTO ──────────┐
 Layer 2 (per-item)─ │ permissions: { edit:true, ... }    │ ── <Can> around each affordance
                     └────────────────────────────────────┘
```

Two structural rules the rest of this section enforces:

- **The `permissions` field is REQUIRED, not optional** (§4.5). A DTO the server forgot to stamp is a *type error* at the serializer/consumer boundary — never a button that silently vanishes at runtime. Fail-closed (missing *key* ⇒ `false`) stays, but it guards forward-compat drift, not a forgotten stamp.
- **Layer-2 tags are read from the fetch that already exists** (D3, §4.4). The chat/explore card reads its `permissions` off the per-card `GET /persona/{id}` (`FullPersonaSnapshot`) it *already* fetches via `useAgent` — never off the hot list DTO, never off the legacy `user_permission`/`PersonaAccessLevel` field.

### 4.1 The `<Can>` primitive (Layer 2)

New file `web/src/components/auth/Can.tsx`. Reads the boolean map on the resource DTO; **fail-closed** — a missing key is `false`, so the server can ship a new action key before any client deploy.

```tsx
// web/src/components/auth/Can.tsx  (NEW)
import type { ResourceActionOf, WithPermissions } from "@/lib/permissions/resource-actions";

// Bare predicate — for imperative sites (disabled=, onClick guards, useMemo).
export function can<R extends WithPermissions>(
  resource: R | null | undefined,
  action: ResourceActionOf<R>,
): boolean {
  return resource?.permissions?.[action] ?? false; // fail-closed on null row / unknown key
}

// Declarative wrapper — the default for JSX affordances.
export function Can<R extends WithPermissions>({
  resource, action, children, fallback = null,
}: {
  resource: R;
  action: ResourceActionOf<R>;   // per-resource union, hand-written — see §4.5
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  return <>{can(resource, action) ? children : fallback}</>;
}
```

Because `permissions` is a **required, exhaustive** `Record<Action, boolean>` per resource (§4.5), `resource.permissions[action]` is statically a `boolean` for a well-typed row — the `?? false` only fires for a `null` resource or a runtime key the client's union predates. Usage collapses a 3-tier hand-written decision to one line:

```tsx
<Can resource={agent} action="feature">
  <FeatureToggle agentId={agent.id} />
</Can>
```

### 4.2 `useUser()` new shape

Drop the injection in `web/src/providers/UserProvider.tsx` (context value, lines 571/576/579). `permissions` was `visibilityPermissions(upToDateUser)` — a client-derived second source of truth. Replace with the server field `admin_capabilities`.

| context field | OLD (`UserProvider.tsx`) | NEW |
|---|---|---|
| `isAdmin` (571) | `effective_permissions.includes(FULL_ADMIN_PANEL_ACCESS)` | **unchanged** |
| `hasAdminAccess` (576) | `hasAnyAdminPermission(visibilityPermissions(user))` | `hasAnyAdminPermission(adminCapabilities)` |
| `permissions` (579) | `visibilityPermissions(user)` | **removed** |
| `adminCapabilities` | — (did not exist) | `upToDateUser?.admin_capabilities ?? EMPTY_PERMISSIONS` |

```tsx
// UserProvider.tsx  value={{ ... }}
isAdmin: (upToDateUser?.effective_permissions ?? EMPTY_PERMISSIONS)
  .includes(Permission.FULL_ADMIN_PANEL_ACCESS),                     // unchanged
adminCapabilities: upToDateUser?.admin_capabilities ?? EMPTY_PERMISSIONS,
hasAdminAccess: hasAnyAdminPermission(
  upToDateUser?.admin_capabilities ?? EMPTY_PERMISSIONS,             // was visibilityPermissions(user)
),
// permissions: REMOVED
```

Add `admin_capabilities?: string[]` to `User` in `web/src/lib/types.ts` (beside `effective_permissions?` L131, `is_group_manager?` L134). `is_group_manager` stays for labels but is **no longer read as a gate** — the server already folded it into `admin_capabilities`.

> Staleness (D8): `admin_capabilities` is computed from the **cached** `is_group_manager` column, while Layer-2 `permissions` and the PEP use *live* scope. Any path that flips manager status — the manual toggle **and external group-sync** — must `recompute_user_permissions` and bust `['me']`, or nav shows while every per-item tag is `false` (dead buttons). See §6.3.

### 4.3 Coarse consumption (Layer 1)

All three coarse seams re-source from `admin_capabilities`; none re-derives. The token set is identical to what `visibilityPermissions()` produced, but computed **server-side** by the PDP, so it can't drift from GATE 2.

| seam | file:line | change |
|---|---|---|
| nav sidebar | `web/src/lib/admin-sidebar-utils.ts:26` `buildItems(permissions,…)` | callers pass `adminCapabilities`; `hasPermission` body unchanged |
| SSR admission | `web/src/lib/auth/requireAuth.ts:108` `requireAdminAuth` | `hasAnyAdminPermission(user.admin_capabilities)` — drop `visibilityPermissions(user)` |
| **per-page guard (NEW, default-deny)** | `web/src/layouts/chromes/AdminSSChrome.tsx:12` | add a per-route check; today this is the **only** gate and it is coarse-only |

**Prerequisite — the frontend token vocabulary must be a superset of what the server can emit** (D4). Nav re-sources from `admin_capabilities`, so every scoped token the server may place in that set must exist as a `Permission` enum member **and** map to an `ADMIN_ROUTES` entry — otherwise the server emits a token the client can't match and a manager's reachable page silently disappears from the nav (and the per-page gate below can't grade it).

The confirmed gap: `Permission.MANAGE_SKILLS` is **absent** from the frontend enum (`web/src/lib/types.ts:65` has no member) and has **no** `ADMIN_ROUTES` entry — this is the same omission the frontend `SCOPED_MANAGER_PERMISSIONS` copy already carries (`web/src/lib/permissions.ts:4` comment admits it drops `MANAGE_SKILLS`). `MANAGE_ACTIONS` exists (`types.ts:78`) with `/admin/actions/{mcp,open-api}` routes, but has no skills sibling. **Before** the nav flips to `admin_capabilities`:

1. Add `MANAGE_SKILLS = "manage:skills"` to the `Permission` enum.
2. Enumerate the skills-manage route(s) in `ADMIN_ROUTES` with `requiredPermission: MANAGE_SKILLS`.
3. Audit the enum + `ADMIN_ROUTES` against the backend `SCOPED_MANAGER_PERMISSIONS` bundle so no scoped token is unrepresentable client-side (the `permissions.ts` bundle itself is deleted — §4.6 — but its *members* must survive as enum + route entries).

**The per-page hole (D5).** `AdminSSChrome` admits any user with *any* admin token, so a manager can SSR-load a `FULL_ADMIN`-only page. (`admin-routes.ts` docstring claims a gate "in `ClientLayout.tsx`" — that file doesn't exist; the enforcement is missing.) The naive fix `if (route && !hasPermission(...))` **fails OPEN**: paths not in `ADMIN_ROUTES` make `route` falsy and skip the check entirely. Real `/admin/*` pages that hit this today: `/admin/systeminfo`, `/admin/groups2/**`, `/admin/federated/[id]`. Gate must **default-deny**:

```tsx
// AdminSSChrome.tsx — after requireAdminAuth() passes
const caps = authResult.user?.admin_capabilities ?? [];
const route = matchAdminRoute(pathname);          // exact / longest-prefix, NOT bare startsWith
// DEFAULT-DENY: an un-enumerated /admin/* path demands the highest token, so a
// manager is redirected and any newly-added page fails closed until registered.
const required = route?.requiredPermission ?? Permission.FULL_ADMIN_PANEL_ACCESS;
if (!hasPermission(caps, required)) {
  return redirect(getFirstPermittedAdminRoute(caps) as Route);
}
```

Enumerate the missing pages in `ADMIN_ROUTES` with their **real** `requiredPermission` (so they resolve by name, not by the fail-closed catch-all):

| path | requiredPermission | why |
|---|---|---|
| `/admin/systeminfo` | `FULL_ADMIN_PANEL_ACCESS` | system diagnostics — admin-only |
| `/admin/federated` (+ `/[id]`) | `FULL_ADMIN_PANEL_ACCESS` | federated connectors have **no scope model**; managers get `403` on every mutation — full-admin only (D6; the "Manage Federated Connector" button is likewise re-gated on `isAdmin`, §5.6) |
| `/admin/groups2` (+ `/[id]`, `/create`) | `MANAGE_USER_GROUPS` *(verify audience)* | groups-management surface; sibling of `/admin/groups` |

> Matching hazard: the current match is `pathname.startsWith(entry.path)`, so `"/admin/groups2".startsWith("/admin/groups")` is `true` — `groups2` would *accidentally* inherit `/admin/groups`'s `MANAGE_USER_GROUPS` rather than being graded explicitly. `matchAdminRoute` must prefer an **exact / longest-prefix segment** match, and every real page must have its own entry — the default-deny catch-all is the backstop, not the primary mechanism.

Because a manager's `admin_capabilities` never contains `FULL_ADMIN_PANEL_ACCESS`, full-admin pages (and every un-enumerated `/admin/*`) redirect managers automatically; manager-reachable pages (`MANAGE_CONNECTORS`, `MANAGE_AGENTS`, `MANAGE_SKILLS`, …) pass. This SSR gate is **defense-in-depth / least-astonishment, not the security boundary** — a manager who reaches a full-admin page still `403`s on every mutating call.

Global **"New X"** buttons go through a hook, not an inline token check:

```ts
// web/src/lib/permissions/useCapabilities.ts  (NEW)
const CAP_TOKEN: Record<string, Permission> = {           // v1 slug → token map
  "connector:create": Permission.MANAGE_CONNECTORS,
  "agent:create":     Permission.ADD_AGENTS,
  "skill:create":     Permission.MANAGE_SKILLS,
  // …
};
export function useCapabilities(required: string[]): boolean {
  const { adminCapabilities } = useUser();               // v1: read /me
  return required.every((c) => adminCapabilities.includes(CAP_TOKEN[c]));
  // later: swap body for POST /capabilities batch (deferred — see §3.6 appendix), same signature
}
```

```tsx
const canCreate = useCapabilities(["connector:create"]);
{canCreate && <NewConnectorButton />}
```

### 4.4 Per-item consumption — collapse the duplication

**Where the tags come from (D3).** Per-card Layer-2 tags are **not** stamped onto the hottest path — the chat/explore agent list is a `MinimalPersonaSnapshot` fetched `get_editable=False` (`backend/onyx/server/features/persona/api.py:501-517`); stamping `edit`/`share`/`view_stats` there would add an N+1 scope resolve per card. Instead, `AgentCard` already fetches the per-card `FullPersonaSnapshot` via `useAgent(agent.id)` (`AgentCard.tsx:64`, a `GET /persona/{id}`) — **that** DTO carries `permissions`, so per-card gating is **zero net-new query**. Never source the tag from the existing `user_permission` / `PersonaAccessLevel` field (`ee/onyx/db/persona_sharing.py:48`): it does **not** reflect scoped-manager edit rights → silent drift. Read `fullAgent.permissions`, fall back to hidden while the per-card fetch is in flight.

**Featured status (4 copies today).** The gate is a *global* manage-agents action (managers get `false`), so the server stamps `agent.permissions.feature`. All four sites become `<Can resource={agent} action="feature">`.

| file:line | reads today | verdict |
|---|---|---|
| `AgentCard.tsx:57` | `hasPermission(permissions, MANAGE_AGENTS)` (injected) | wrong → managers see it |
| `ShareAgentModal.tsx:79` | `hasPermission(permissions, …)` (injected) | wrong |
| `AgentEditorPage.tsx:492` | `hasPermission(permissions, …)` (injected) | wrong |
| `AgentRowActions.tsx:68` | `hasPermission(user.effective_permissions, …)` (raw) | correct — but the raw/injected fork is exactly what devs get wrong |

→ one server field (`feature`), one primitive; the `MANAGE_AGENTS` token check disappears from all four.

**Ownership-as-gate.** `checkUserOwnsAgent` (`web/src/lib/agents/utils.ts:10`) is wrong in both directions — a manager/editor who can edit but doesn't own is hidden; a readable-not-editable row is shown → 403 on click. Note the tag now carries the **owner bypass** for free: the projection stamps `edit`/`share` true for a plain owner *and* an in-scope manager (§3.3, §5.1), so no client-side owner check is reintroduced.

- `AgentCard.tsx:61` `isOwnedByUser` used to gate edit/share → replace with `can(fullAgent, "edit")` / `can(fullAgent, "share")` (read off the per-card DTO, above).
- `AgentsNavigationPage.tsx:79` — **keep** `checkUserOwnsAgent`; it only filters the "Your Agents" tab (a label, not a gate).

**Doc-set double-fetch.** `page.tsx Main()` (L353–364) fetches `useDocumentSets()` **and** `useDocumentSets(true)` (`hooks.tsx:10`, two SWR keys), then set-diffs to synthesize editability (`isEditable = editableDocumentSets.some(…)`, L197; union L174–176).

```
BEFORE:  GET /document-set  +  GET /document-set?editable=true  →  client set-diff  →  isEditable
AFTER:   GET /document-set  (rows carry permissions.edit)       →  can(ds, "edit")
```

Delete the second fetch (`SWR_KEYS.documentSetsEditable`), the union, and the `.some()` diff; `useDocumentSets(getEditable)` loses its parameter. Render `<Can resource={ds} action="edit">` / `action="delete"`.

### 4.5 Hand-written per-resource action unions (no codegen in v1)

The action strings must match the server's stamped keys at compile time, so a typo (`action="feaure"`) fails `tsc`, not silently fails-closed at runtime. **There is no codegen pipeline today**, and standing one up is not worth v1 — the vocabulary is 7 small unions. **Hand-write them** (they change about as often as the backend gate set — rarely) and bind each to its DTO type.

```ts
// web/src/lib/permissions/resource-actions.ts  (HAND-WRITTEN — one small union per resource)
export type ResourceActionMap = {
  ConnectorIndexingStatusLite: "edit" | "delete" | "manage_access" | "publish";
  DocumentSetSummary:          "edit" | "delete" | "manage_access" | "publish";
  PersonaSnapshot: "edit" | "share" | "view_stats" | "delete" | "feature" | "list" | "reorder" | "publish";
  CustomSkillResponse:         "edit" | "manage_access" | "delete" | "publish";
  MCPServer:   "edit" | "delete" | "authenticate" | "manage_status";
  ToolSnapshot:"edit" | "delete" | "toggle";
  UserGroup:   "manage" | "delete" | "edit_permissions" | "edit_token_limits";
};

// REQUIRED + exhaustive per resource. A DTO the server forgot to stamp — or
// stamped with a missing action — is a *type* error here, not a vanished button.
export interface WithPermissions<K extends keyof ResourceActionMap = keyof ResourceActionMap> {
  __resource: K;                                   // phantom tag, set once in the DTO's parser
  permissions: Record<ResourceActionMap[K], boolean>;
}
export type ResourceActionOf<R> =
  R extends { __resource: infer K extends keyof ResourceActionMap }
    ? ResourceActionMap[K]
    : never;
```

Each DTO type carries a `__resource: "PersonaSnapshot"` phantom tag, so `<Can resource={agent} action="…">` only accepts that resource's actions, and its `permissions` map must be present and complete.

**Required, not optional — the whole point of D4.** With `permissions?: Record<string, boolean>` (optional), a serializer that forgets a resource yields `undefined` → `<Can>` fail-closes → the button *silently disappears* with no error anywhere. Making the field **required** on both ends turns "forgot to stamp" into a hard failure:

- **Backend:** the Pydantic field is `permissions: dict[str, bool]` with **no default** — a `from_model` that doesn't set it raises at construction.
- **Frontend:** `Record<ResourceActionMap[K], boolean>` is exhaustive — a DTO parser that omits the map, or a stamp loop that drops an action, fails `tsc`.

**Backend coverage test — closes the "add an action, forget to register it" hole.** Type-requiredness catches a *forgotten map*; it does not catch a *new scoped route whose action was never added to the stamp loop / union*. A cheap backend test walks the router and asserts every mutating scoped route has a home:

```py
# backend/tests/external_dependency_unit/auth/test_scoped_route_coverage.py
def test_every_scoped_mutation_maps_to_a_stamped_action():
    # routes carrying require_permission(..., allow_scope=True) OR assert_within_scope in the body
    for route in scoped_mutating_routes(app):
        resource, action = ROUTE_TO_ACTION[route.endpoint]      # explicit registry, must be total
        assert action in STAMPED_ACTIONS[resource], \
            f"{route.path}: '{action}' not stamped for {resource}"
```

`STAMPED_ACTIONS[resource]` is the exact key set the projection stamps (§3.3) and mirrors the hand-written frontend unions. Add a scoped route without registering its action → red CI, not a phantom `403`. This pairs with the `project == enforce` contract test (§6.1): that one proves each *stamped* key is correct; this one proves no *gate* is unstamped.

The batch `POST /capabilities` probe stays deferred (§3.6 appendix) — `useCapabilities` reads `admin_capabilities` in v1; nothing here depends on it.

### 4.6 Deletions

| delete | file:line | replaced by |
|---|---|---|
| `visibilityPermissions()` + its export | `web/src/lib/permissions.ts:33` | server `admin_capabilities` (§4.2) |
| `SCOPED_MANAGER_PERMISSIONS` (frontend copy) | `web/src/lib/permissions.ts:7` | server-owned bundle — **but first** ensure every member survives as a `Permission` enum value + `ADMIN_ROUTES` entry (`MANAGE_SKILLS` is the missing one, §4.3); the *bundle constant* goes, the *tokens* must stay |
| `permissions` context field + all `useUser().permissions` reads | `UserProvider.tsx:579`; `AgentCard.tsx:55`, `ShareAgentModal.tsx`, `AgentEditorPage.tsx:491` | `adminCapabilities` (coarse) / `resource.permissions` (per-item) |
| `canUpdateFeaturedStatus` (×4) | `AgentCard.tsx:57`, `ShareAgentModal.tsx:79`, `AgentEditorPage.tsx:492`, `AgentRowActions.tsx:68` | `<Can action="feature">` |
| `checkUserOwnsAgent` **as edit/share gate** | `AgentCard.tsx:61` | `can(fullAgent,"edit"/"share")` — fn kept only for the "Your Agents" label (`AgentsNavigationPage.tsx:79`) |
| editable doc-set double-fetch + set-diff | `page.tsx:361-364,174-176,197`; `hooks.tsx:10` param; `SWR_KEYS.documentSetsEditable` | single fetch + `can(ds,"edit")` |
| fail-OPEN per-page gate (naive `if (route && …)`) | proposed `AdminSSChrome.tsx` guard | default-deny gate + enumerated routes (§4.3) |

`hasPermission` / `hasAnyAdminPermission` / `ADMIN_ROUTES` / `buildItems` / `requireAdminAuth` survive unchanged in logic — only their **input** flips from client-derived `visibilityPermissions(user)` to server `admin_capabilities`, and `ADMIN_ROUTES` **gains** the `MANAGE_SKILLS` + `systeminfo`/`groups2`/`federated` entries (§4.3).

---

_Files read to verify:_ `web/src/lib/permissions.ts` (bundle L7, `visibilityPermissions` L33, comment L4 admits `MANAGE_SKILLS` drop), `web/src/lib/types.ts` (Permission enum L65 — **no `MANAGE_SKILLS` member**; `MANAGE_ACTIONS` L78), `web/src/lib/admin-routes.ts` (`requiredPermission` L86; `/admin/actions/*` = `MANAGE_ACTIONS`; **no** skills / `systeminfo` / `groups2` / `federated` entry; match is `startsWith`), `web/src/app/admin/{systeminfo,groups2,federated}` (real un-enumerated `/admin/*` pages), `web/src/lib/auth/requireAuth.ts:108`, `web/src/layouts/chromes/AdminSSChrome.tsx`, `web/src/providers/UserProvider.tsx` (ctx value 571/576/579), `web/src/lib/admin-sidebar-utils.ts` (buildItems L26), `web/src/lib/agents/utils.ts:10`, `web/src/sections/agents/AgentCard.tsx` (55/57/61; `useAgent(agent.id)` L64 — the per-card `FullPersonaSnapshot` fetch the tags ride on), `web/src/sections/modals/ShareAgentModal.tsx:79`, `web/src/refresh-pages/AgentEditorPage.tsx:492`, `web/src/refresh-pages/admin/AgentsPage/AgentRowActions.tsx:68`, `web/src/refresh-pages/AgentsNavigationPage.tsx:79`, `web/src/app/admin/documents/sets/{hooks.tsx,page.tsx}`. Deviations corrected above: (1) `canUpdateFeaturedStatus` is **4** copies (`AgentRowActions.tsx:68` is a fourth, and the only correct one); (2) the per-page gate `admin-routes.ts` attributes to `ClientLayout.tsx` does not exist — per-page enforcement is genuinely absent, and the naive replacement fails OPEN on un-enumerated `/admin/*`; (3) `MANAGE_SKILLS` is absent from the frontend `Permission` enum and `ADMIN_ROUTES`, so the nav re-source silently hides scoped-skills managers until it is added.

---

## 5. Affordance → Action Mapping (complete)

All 49 mis-gated affordances, grouped by domain. **Scope legend** for the `resource.permissions[...]` map — *each action's tag is stamped by **its own** real gate (D2), never one filter per resource*:

- **M** — scoped-manager `true` iff in-scope (admin also `true`).
- **A** — global/admin token only; managers → `false`.
- **O** — owner/creator-or-admin; managers → `false` **unless they own it**.
- **M|O** — union: scoped **OR** owner/creator **OR** admin (owner-bypass — the correction; stamping only the scoped term would hide the button from a plain owner/creator on their own resource).
- **O|A** — owner-or-global (owner bypass, but **not** the scoped-manager path).

Coarse rows use `hasPermission(adminCapabilities, X)` / `useCapabilities([...])`; truly FULL_ADMIN rows use `isAdmin`. Fail-closed: a missing key ⇒ `false`.

`project == enforce` by construction (§3.1a): the projection stamps each `permissions[action]` by calling the **same** `can_<action>(user, resource, db)` helper the write-side guard (`assert_*`) calls, and the contract test calls it too — no re-derivation. The per-action real-gate → scope-class mapping these rows draw from is the action-level table in §3.3.

### 5.1 Agents / Personas — 18 (DTO map `{edit:M, delete:O|A, share:M, feature:A, publish:O|A, list:A, reorder:A, view_stats:O}`)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Edit btn (admin list) | `refresh-pages/admin/AgentsPage/AgentRowActions.tsx:159` | none — row shown for every list item | `permissions.edit` (M) |
| List/Unlist (`toggleAgentListed`) | `AgentRowActions.tsx:176` | none | `permissions.list` (A) |
| Set/Remove Featured | `AgentRowActions.tsx:195` | `hasPermission(user.effective_permissions, …)` — *the one correct copy* | `permissions.feature` (A) |
| Share btn (admin list) | `AgentRowActions.tsx:239` | none | `permissions.share` (M) |
| Stats btn | `AgentRowActions.tsx:251` | none | `permissions.view_stats` (O — owner/admin, `user_can_view_assistant_stats`) |
| Delete (`deleteAgent`) | `AgentRowActions.tsx:265` | none | `permissions.delete` (O\|A) |
| Drag-reorder (`handleReorder`) | `refresh-pages/admin/AgentsPage/AgentsTable.tsx:123` | none | `isAdmin` (FULL_ADMIN) / `permissions.reorder` (A) |
| Edit btn (chat/explore card) | `sections/agents/AgentCard.tsx:161` | `isOwnedByUser` = `checkUserOwnsAgent` | `permissions.edit` (M) |
| Share btn (chat/explore card) | `AgentCard.tsx:176` | `isOwnedByUser` | `permissions.share` (M) |
| Quick-feature star | `AgentCard.tsx:149` | `isOwnedByUser && businessTier` | `permissions.feature` (A) |
| `canUpdateFeaturedStatus` **copy #1 (wrong)** | `AgentCard.tsx:57` | `hasPermission(permissions, …)` — injected tokens | `permissions.feature` (A) |
| `canUpdateFeaturedStatus` **copy #2 (wrong)** | `sections/modals/ShareAgentModal.tsx:79` | `hasPermission(permissions, …)` — injected tokens | `permissions.feature` (A) |
| Feature switch (share modal) | `ShareAgentModal.tsx:345` | rendered iff `canUpdateFeaturedStatus` (copy #2) | `permissions.feature` (A) |
| "Publish This Agent" switch (`isPublic`) | `ShareAgentModal.tsx:340` | none — any sharer can toggle org-public | `permissions.publish` (O\|A) |
| `canUpdateFeaturedStatus` **copy #3 (wrong)** | `refresh-pages/AgentEditorPage.tsx:492` | `hasPermission(permissions, …)` — injected tokens | `permissions.feature` (A) |
| Feature control (editor) | `AgentEditorPage.tsx:1545` | rendered iff `canUpdateFeaturedStatus` (copy #3) | `permissions.feature` (A) |
| Delete agent (`handleDeleteAgent`) | `AgentEditorPage.tsx:889` | none — page-reach only | `permissions.delete` (O\|A) |
| Share/publish modal open | `AgentEditorPage.tsx:1083` | none — page-reach only | `permissions.share` (M) |

**Note — where the chat-card tags come from (D3).** The chat/explore card's `edit`/`share`/`view_stats` tags are stamped on the per-card **`GET /persona/{id}`** (`FullPersonaSnapshot`) that `AgentCard` **already** fetches via `useAgent` (`AgentCard.tsx:64`) — **zero net-new query**. They are **not** stamped on the `MinimalPersonaSnapshot` chat/explore *list* (fetched `get_editable=False`, `persona/api.py:501-517` — the hottest path; leave it untagged), and are **never** sourced from `user_permission`/`PersonaAccessLevel` (`persona/models.py:398`), which does **not** reflect scoped-manager edit rights (silent drift). Admin-list rows stamp per-row from a preload-once editable-id set (connectors template).

**Note — the gates (D2).** `edit`/`share` = **read-editable AND scoped-assert** — `_add_user_filters(get_editable=True)` (`db/persona.py:82`) **AND** `_assert_persona_update_within_managed_scope`→`assert_within_scope` (share adds EE `_assert_group_share_within_scope`, `ee/onyx/db/persona.py:104,161`); **never** the editable filter alone (superset union → over-reports → 403). `view_stats` = **O** (reclassified M→O): `user_can_view_assistant_stats` (`ee/onyx/db/analytics.py:339`) = owner **OR** FULL_ADMIN — **not** the editable filter. `delete`/`publish` = **O|A** (reclassified A→O|A): `global MANAGE_AGENTS OR owner OR owner-group member` — a plain owner *can* delete/org-publish their own agent, but the filter excludes scoped-manager rels, so ≠ `edit`'s M.

**Note — the featured fork / labels.** `canUpdateFeaturedStatus` exists in **three injected-token copies** (`AgentCard:57`, `ShareAgentModal:79`, `AgentEditorPage:492`) vs the one correct `effective_permissions` copy (`AgentRowActions:68`) — collapse all four to `<Can resource={agent} action="feature">`. `checkUserOwnsAgent` stays only as the **"Your Agents"** label (`AgentsNavigationPage.tsx:79`), never as an edit/share gate. Coarse **"New Agent"** (`AgentsNavigationPage.tsx:105`, currently `hasPermission(permissions, ADD_AGENTS)` off injected tokens) → `useCapabilities(['agent:create'])` off `admin_capabilities`.

### 5.2 Actions / MCP — 9 (MCP `MCPServer {edit:M|O, delete:O, authenticate:O, manage_status:O}`; OpenAPI `ToolSnapshot {edit:M|O, delete:A, toggle:A}`)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Edit MCP server | `sections/actions/MCPActionCard.tsx:284` | none — page-reach only | `permissions.edit` (M\|O) |
| Delete MCP server | `MCPActionCard.tsx:213` | none | `permissions.delete` (O) |
| Authenticate (pending) | `MCPActionCard.tsx:211` | none | `permissions.authenticate` (O) |
| Disconnect (deauth) | `MCPActionCard.tsx:209` | none | `permissions.authenticate` (O) |
| Refresh tools / status | `MCPActionCard.tsx:257` | none | `permissions.manage_status` (O) |
| Edit OpenAPI action | `sections/actions/ActionCard.tsx:131` (via `OpenApiActionCard`) | none | `permissions.edit` (M\|O) |
| Delete OpenAPI action | `sections/actions/OpenApiActionCard.tsx:130` | none | `permissions.delete` (A) |
| Toggle tools (enable/disable) | `OpenApiActionCard.tsx:123` | none | `permissions.toggle` (A) |
| Coarse "Add MCP Server" / "Add OpenAPI Action" | `sections/actions/MCPPageContent.tsx:495`, `OpenApiPageContent.tsx:358` | none | `useCapabilities(['action:create'])` (coarse `MANAGE_ACTIONS`) |

**Note.** **`edit` is `M|O` (owner/creator bypass), not `M` (D2):** MCP edit = `_ensure_mcp_server_editable` (`mcp/api.py:1376`) = `FULL_ADMIN OR server.owner == user.email OR scoped` — MCP ownership is by **EMAIL** (`:1386`; DTO ships `owner:str`); OpenAPI edit = `_get_editable_custom_tool` (`tool/api.py:84`) = `FULL_ADMIN OR tool.user_id == user.id (creator) OR scoped` (`_assert_action_within_managed_scope:62`; `ToolSnapshot` ships `user_id`). Stamping only the scoped term would hide **Edit** from a plain owner/creator on their own resource. MCP delete/authenticate/disconnect/status stay **owner-only** (`_ensure_mcp_server_owner_or_admin`, `:1358`) — the DTO map is the only place that O-vs-M|O distinction survives to the client. OpenAPI `delete`/`toggle` are `MANAGE_ACTIONS` **no `allow_scope`** ⇒ `A`.

### 5.3 Skills — 8 (`CustomSkillResponse {edit:M, delete:A, manage_access:M, publish:A}`)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Skills-manage **page access** | `layouts/craft/CraftManageLayout.tsx:22` | `hasPermission(effective_permissions, FULL_ADMIN_PANEL_ACCESS)` → redirect | coarse `hasPermission(adminCapabilities, MANAGE_SKILLS)` |
| "Manage" entry surfacing | `refresh-pages/UserSkillsPage` (routes to manage) | same FULL_ADMIN redirect | coarse `MANAGE_SKILLS` |
| Edit visibility (grants) | `refresh-pages/admin/SkillsPage/CustomSkillRowActions.tsx:60` | none — no per-row gate at all | `permissions.manage_access` (M) |
| Replace bundle (edit) | `CustomSkillRowActions.tsx:71` | none | `permissions.edit` (M) |
| Disable / Re-enable | `CustomSkillRowActions.tsx:81` | none | `permissions.edit` (M) |
| Delete skill | `CustomSkillRowActions.tsx:92` | none | `permissions.delete` (A) |
| Share/grant modal (group grants) | `refresh-pages/admin/SkillsPage/ShareSkillModal.tsx` + `SkillSharePicker.tsx` | none | `permissions.manage_access` (M) |
| Coarse "Upload skill" (create) | `refresh-pages/admin/SkillsPage.tsx` (`UploadSkillModal`) | none | `useCapabilities(['skill:create'])` (coarse `MANAGE_SKILLS`) |

**Note.** The whole page hides behind a **FULL_ADMIN redirect** (`CraftManageLayout`), so a manager holding scoped `MANAGE_SKILLS` (which has **no frontend token today** — see `permissions.ts:5` comment) can't reach it at all → **drop to coarse `admin_capabilities` `MANAGE_SKILLS`**, and add the token. `CustomSkillRowActions` has **zero per-item gating** — every row shows edit/replace/toggle/delete; delete is `FULL_ADMIN` (A), the rest scoped (`MANAGE_SKILLS allow_scope`); `granted_group_ids` already ships on the DTO.

### 5.4 Groups — 6 (`UserGroup {manage:M (per-group), delete:A, edit_permissions:A, edit_token_limits:A}`)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Open/Manage group (row → edit) | `refresh-pages/admin/GroupsPage/GroupCard.tsx:70` | none — no **per-group** manager signal | `permissions.manage` (M, per-group) |
| Add members | `refresh-pages/admin/GroupsPage/EditGroupPage.tsx:129` | none — page-reach only | `permissions.manage` (M) |
| Delete group | `EditGroupPage.tsx:126` | none | `permissions.delete` (A) |
| Toggle group permissions | `refresh-pages/admin/GroupsPage/GroupPermissionsSection.tsx:74` | data fetch gated on `isAdmin` (`:107`); section still renders | `permissions.edit_permissions` (A) |
| Add/remove + save token limits | `refresh-pages/admin/GroupsPage/TokenLimitSection.tsx:154/144` | `disabled` from **tier only**, not role | `isAdmin` (PUT/DELETE = FULL_ADMIN); POST scoped |
| Coarse "New Group" | `refresh-pages/admin/GroupsPage/index.tsx:69` | `actionLabel={isAdmin ? "New Group" : undefined}` — managers hidden | `useCapabilities(['group:create'])` (coarse `MANAGE_USER_GROUPS`) |

**Note.** The **missing signal is per-group `manage`** — `is_group_manager` on `/me` is global; the snapshot already carries `manager_ids`, so `permissions.manage` is `assert_manages_group` (`auth/scoped_permissions.py:92`) for *this* group = `group_id ∈ managed set OR global MANAGE_USER_GROUPS` — a **single-group membership** gate (D2), **not** `within_managed_scope_clause`/the editable filter, and `manager_ids` on the snapshot is *not* itself the gate. Token-limit **PUT/DELETE are FULL_ADMIN** (`ee/.../token_rate_limits/api.py`) → `isAdmin`, not `edit_token_limits`; only POST is scoped.

### 5.5 Doc sets — 3 (`DocumentSetSummary {edit:M, delete:A, manage_access:M, publish:A}`)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Edit row | `app/admin/documents/sets/page.tsx:204` (`EditRow`, `isEditable`) | client **set-diff** of two fetches (`useDocumentSets()` vs `useDocumentSets(true)`, `page.tsx:359-364`, `:197`) | `permissions.edit` (M) |
| Delete (`DeleteButton`) | `sets/page.tsx:308` | gated by same client set-diff `isEditable` | `permissions.delete` (A) |
| Make-public / publish badge | `sets/page.tsx:300` | none — public/private shown, not gated | `permissions.publish` (A) |

**Note.** Kill the **double-fetch + client set-diff** (`hooks.tsx:10-27` + `page.tsx:359-364`) — one list call carrying `permissions.edit` replaces it. DELETE route is `MANAGE_DOCUMENT_SETS` **no `allow_scope`** ⇒ delete `A`; **make-public ⇒ `publish:A`** (managers can edit a scoped set but not publish it org-wide).

### 5.6 Connectors (cc_pair) — 3 (the GOOD domain: `is_editable_for_current_user` already ships — the template)

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Federated connector "Manage" button | `app/admin/indexing/status/CCPairIndexingStatusTable.tsx:308` | ungated — 403s for managers (hard-coded `is_editable: false`; **no scope model** for federated) | **`isAdmin` / coarse `MANAGE_CONNECTORS`** (D6 — decided admin-only); `/admin/federated/[id]` enumerated **FULL_ADMIN** in `ADMIN_ROUTES` |
| Edit gate (detail page) | `app/admin/connector/[ccPairId]/page.tsx:188-190` | client **re-derives**: `is_editable_for_current_user \|\| (MANAGE_CONNECTORS && !FULL_ADMIN && …)` | pure `permissions.edit` (M) — drop the OR-fallback |
| Make org-public (publish) | `[ccPairId]/page.tsx` access controls | none | `permissions.publish` (A) |

**Note.** Pause/Delete already gate correctly on `is_editable_for_current_user` (`page.tsx:488`, `:481`) — **this is the template** the other domains copy. **Federated connectors have no `cc_pair` row and no scope model**, so the ungated "Manage Federated Connector" button 403s for managers today. **Decided (D6): gate it on `isAdmin` / global `MANAGE_CONNECTORS` and enumerate `/admin/federated/[id]` as `FULL_ADMIN` in `ADMIN_ROUTES`** — admin-only in v1 (no `permissions.edit` until federated grows a scope source). This resolves former §6.6 open-decision #1 (no longer open). The detail-page edit gate still **re-derives policy client-side** (`MANAGE_CONNECTORS && !FULL_ADMIN`) instead of trusting `permissions.edit` alone — drop the OR-fallback.

### 5.7 Nav / page access — 2

| Surface | File:line | Current gate (compressed) | New gate |
|---|---|---|---|
| Admin page SSR access | `layouts/chromes/AdminSSChrome.tsx:13` | coarse admission only — **no per-page `requiredPermission`** ⇒ manager can SSR-load FULL_ADMIN pages | **per-page gate, DEFAULT-DENY**: matched → `hasPermission(adminCapabilities, ADMIN_ROUTES[path].requiredPermission)`; **unmatched `/admin/*` → require `FULL_ADMIN_PANEL_ACCESS`** (redirect managers) |
| Admin sidebar items | `lib/admin-sidebar-utils.ts:36` `buildItems()` | `hasPermission(permissions, …)` off **injected** `visibilityPermissions()` | re-source `permissions` from `admin_capabilities`; delete `visibilityPermissions` |

**Note.** `AdminSSChrome` is **the only page-access gate** and it's coarse-only — add the per-page check keyed on the matched `ADMIN_ROUTES[path].requiredPermission`, sourced from `admin_capabilities` (so a scoped manager reaches `/admin/agents` but a FULL_ADMIN-only route SSR-redirects). **Default-deny (D5):** a naive matched-only gate **no-ops** on `/admin/*` paths **not** in `ADMIN_ROUTES` (`systeminfo`, `groups2`, `federated/[id]`) → **fails OPEN** (managers reach them). Fix: an **unmatched `/admin/*` requires `FULL_ADMIN_PANEL_ACCESS`** (redirect managers), and the missing pages are **enumerated in `ADMIN_ROUTES`** with their real `requiredPermission` (`/admin/federated/[id]` → `FULL_ADMIN`, per D6). `buildItems()` and `requireAdminAuth` (`lib/auth/requireAuth.ts:108`) both re-source from `admin_capabilities`; **`visibilityPermissions` (`lib/permissions.ts:33`) is deleted**, closing root cause #1 (the drifting second source of truth).

**Roll-up:** 18 + 9 + 8 + 6 + 3 + 3 + 2 = **49**. Every row's **New gate** is server-authoritative — a `permissions[...]` key stamped by the projection via the shared `can_<action>` helper (§3.1a), a coarse `admin_capabilities` check, or `isAdmin` for the genuinely FULL_ADMIN affordances (agent reorder, token-limit PUT/DELETE, **federated "Manage"**). The scope taxonomy is richer than M/A: **O|A** (persona `delete`/`publish` — owner bypass, no scoped path) and **M|O** (tool/MCP `edit` — owner/creator bypass by `user_id`/`email`) carry owner/creator affordances a pure-scoped stamp would wrongly hide, and **O** (`view_stats`, MCP delete/authenticate/status) resolves owner-or-admin. The client is reduced to a pure `<Can>` renderer.

---

_Provenance: every `file:line` in §5 was verified against the repo `HEAD` (branch `perms-pr6-manager-ui-scoped-nav`). Notable confirmations while writing this table: `canUpdateFeaturedStatus` exists in **4** copies (not 3 — `AgentRowActions.tsx:68` is a fourth, and the one correct one); the doc-set double-fetch, the `is_editable_for_current_user` connector template, the `CraftManageLayout` FULL_ADMIN skills redirect, and the `visibilityPermissions` injection point are all present; and the per-page gate that `admin-routes.ts` claims lives in `ClientLayout.tsx` does **not** exist (per-page enforcement is genuinely absent — `AdminSSChrome` is the only gate). Per-gate D2/D5/D6 verifications baked in: persona `view_stats` = `user_can_view_assistant_stats` (owner ∨ FULL_ADMIN, `ee/onyx/db/analytics.py:339`), **not** the editable filter (M→O); persona `edit`/`share` = read-editable **AND** `_assert_persona_update_within_managed_scope`/EE `_assert_group_share_within_scope` (not `get_editable` alone); MCP `edit` owner is by **EMAIL** (`mcp/api.py:1386`) and Tool `edit` has a **creator** bypass (`tool/api.py:100`) — both M→M|O; persona `delete`/`publish` are owner-or-global (A→O|A); federated connectors have no scope model → admin-only (D6); the per-page SSR gate must **default-deny** unmatched `/admin/*` (D5, else it fails open on `systeminfo`/`groups2`/`federated/[id]`)._

---

## 6. Testing, Rollout & PR Roadmap

### 6.1 Contract test — project == enforce (the anti-drift guarantee)

The guarantee is no longer "the read filter is a faithful mirror" — it is **one shared decision helper** (§3.1a). Each tricky guard's boolean is extracted into `can_<action>(user, resource, db) -> bool`; `assert_<action>` calls that helper then raises (behavior byte-for-byte unchanged), the projection stamps `resource.permissions[action]` by calling the **same** helper, and the contract test calls the **same** helper. Because `assert_*` now *calls* `can_*`, `project == enforce` is **structural**, not a coincidence a test has to keep re-checking.

Two tests hold the line.

**(a) Helper-parity contract test.** The centerpiece. It does **not** run a parallel `get_editable=True` read query (v1's drift risk); it drives the **real `assert_*` guard** and asserts the helper the projection stamps equals the guard's decision.

```py
# backend/tests/external_dependency_unit/auth/test_permission_projection_contract.py
# extends the scoped-perms fixtures in test_scoped_permissions.py

ACTORS = ["admin", "manager_in_scope", "manager_out_of_scope", "owner", "viewer"]

# (resource, action) -> the SAME can_* helper the projection stamps AND assert_* calls (§3.1a).
# One entry per per-resource-gated action (M / O / M|O / O|A) in §3.3 + the D2 table.
CAN = {
  ("persona","edit"):       can_edit_persona,        # M   editable ∧ within_scope
  ("persona","share"):      can_share_persona,       # M   editable ∧ group_share_within_scope
  ("persona","view_stats"): can_view_persona_stats,  # O   owner ∨ FULL_ADMIN (analytics.py:339)
  ("persona","delete"):     can_delete_persona,      # O|A owner-bypass filter (is_for_edit=True)
  ("persona","publish"):    can_publish_persona,     # O|A owner ∨ global MANAGE_AGENTS
  ("tool","edit"):          can_edit_custom_tool,    # M|O admin ∨ creator(user_id) ∨ scoped
  ("mcp_server","edit"):    can_edit_mcp_server,     # M|O admin ∨ owner(email) ∨ scoped
  ("user_group","manage"):  can_manage_group,        # M   per-group (managed set ∨ global)
  ("document_set","edit"):  can_edit_document_set,    # M   editable-id membership
  ("cc_pair","edit"):       can_edit_cc_pair,         # M   is_editable_for_current_user
  # …share/manage_access variants stamped by their own can_* helper
}

@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize(("resource_kind","action"), list(CAN))
def test_helper_matches_guard(db_session, actor, resource_kind, action):
    u, r = make_actor(actor), make_resource(resource_kind, actor)
    helper_says = CAN[(resource_kind, action)](u, r, db_session=db_session)  # projection's boolean
    raised = guard_raised(resource_kind, action, u, r, db_session)           # drives the real assert_* guard
    assert helper_says is (not raised), f"DRIFT {resource_kind}.{action} for {actor}"
```

`guard_raised` invokes the actual `_assert_persona_update_within_managed_scope` / `_ensure_mcp_server_editable` / `assert_manages_group` / … and reports whether it raised `OnyxError`. A policy edit to `within_scope`/`manages_group` (`auth/scoped_permissions.py:55,92`) moves **both** sides at once or fails CI — this is what makes drift structurally impossible. If a cell fails, the bug is the read wrapper's *composition* (forgot the `editable ∧` for persona, or stamped only the scoped term for tool/mcp) — **never** a reason to relax a guard.

**A-class (global-token) actions** — `feature`, `list`, `reorder`, and the pure-global `delete`/`toggle` — have **no per-resource guard**; the gate is the route's `require_permission(perm, allow_scope=False)`. They stamp constant-per-row from `effective_permissions`, so they are asserted against token membership directly (managers → `false`):

```py
GLOBAL = [("persona","feature",MANAGE_AGENTS), ("persona","list",MANAGE_AGENTS),
          ("persona","reorder",FULL_ADMIN_PANEL_ACCESS), ("tool","toggle",MANAGE_ACTIONS),
          ("tool","delete",MANAGE_ACTIONS), ("document_set","delete",MANAGE_DOCUMENT_SETS), …]

@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize(("resource_kind","action","token"), GLOBAL)
def test_global_token_actions(db_session, actor, resource_kind, action, token):
    u, r = make_actor(actor), make_resource(resource_kind, actor)
    dto = to_dto(r, user=u, db=db_session)
    assert dto.permissions[action] is (token in get_effective_permissions(u))
```

The matrix is **{admin, manager-in-scope, manager-out-of-scope, owner, viewer} × 7 resources**, so every `M`/`A`/`O`/`M|O`/`O|A` cell in §3.3 is asserted in both directions (granted *and* denied), including the D2 owner/creator bypasses (a plain owner sees `edit` on their own tool/mcp/persona; a manager does **not** see `feature`).

**(b) Route-coverage test (D4).** Closes the "add a scoped route, forget to register its action" hole. Every mutating scoped route must map to an action that is (1) in the hand-written per-resource union (§4.5) and (2) stamped by the projection.

```py
# backend/tests/external_dependency_unit/auth/test_scoped_route_coverage.py
def test_every_mutating_scoped_route_is_stamped():
    # routes whose dep is require_permission(..., allow_scope=True) OR whose body
    # calls assert_within_scope / assert_manages_group (introspected from the router)
    for route in discover_scoped_mutations():
        key = ROUTE_ACTION.get(route.endpoint)                       # (resource, action) — hand-maintained
        assert key, f"{route.path}: no (resource,action) mapping"
        resource, action = key
        assert action in HAND_ACTIONS[resource], f"{action} missing from {resource} action union (§4.5)"
        assert key in CAN or key in GLOBAL_KEYS, f"{key} not stamped by the projection"
```

Combined with the **required** (not optional) `permissions` DTO field (§4.5), a forgotten stamp is a compile error on the client and a red test on the server — never a silently-vanishing button.

**E2E (Playwright).** One scenario per resource is overkill; assert the whole-surface invariant once — a scoped manager, in-scope on group G, sees *exactly* the in-scope affordances:

```
seed: manager M -> scope {G}; agent Ain∈G, Aout∉G; docset Din∈G, Dout∉G
assert: nav shows Agents+DocSets+Groups (admin_capabilities);  NOT LLMs/Settings (FULL_ADMIN)
assert: <Can resource=Ain action="edit"> renders;  <Can resource=Aout action="edit"> absent
assert: Delete on Ain absent (delete=A);  Share on Ain present (share=M)
assert: direct SSR GET /admin/configuration/llm -> redirect (per-page default-deny, §3.5/D5)
assert: direct SSR GET /admin/systeminfo (unmapped /admin/* path) -> redirect (fails CLOSED, D5)
```

### 6.2 Security note — flags are affordance-only

The `permissions{}` map and `admin_capabilities` control **rendering, not authority**. They hide buttons the user would be 403'd on. The real boundary is unchanged — and after D1 the projection is **literally the same code** the PEP's boolean runs, so there is no second decision surface to audit:

| Layer | Artifact | Property |
|---|---|---|
| PEP (real gate) | `assert_*` (e.g. `auth/scoped_permissions.py:55`) → now calls `can_*`, then raises | A forged/replayed request with the button "un-hidden" still hits the PEP and 403s. |
| Decision (truth) | `can_<action>` / `within_scope` / `manages_group` (§3.1a) | Single boolean; guard, projection, and contract test all call it. |
| Projection (hint) | `resource.permissions[a]`, `admin_capabilities` | Untrusted by the server; never an input to an authz decision. |

Two invariants the review must hold:
- **Fail-closed by shape:** every helper's terminal branch returns `False` (unknown authority, empty managed scope, missing resource state all deny); on the client a missing action key ⇒ `false`. Forward-compatible — the server ships a new key before any client deploy.
- **No new decision surface:** the extraction only *relocates* the boolean. The **existing PR1–5 enforcement suite is the proof security is unchanged** — it must stay green with zero edits. If a contract-test cell fails, it is a *projection-composition* bug, never a reason to relax the PEP.

### 6.3 Cache hygiene (React Query) — incl. cached-vs-live manager status (D8)

`permissions{}` rides in the resource DTO, so any mutation that changes who-can-do-what must invalidate the resource query. Additionally, Layer-1 `admin_capabilities` is computed from the **cached** `is_group_manager` column, while Layer-2 `permissions{}` and the PEP use **live** scope. If those drift apart, the failure is silent and ugly: nav shows (cached `is_group_manager=true`) but every per-item `permissions[...]` is `false` → **dead buttons** (or the inverse — hidden nav for a real manager).

**Rule (D8):** *every* manager-status change must `recompute_user_permissions(user)` server-side **and** bust `['me']` client-side — not only the manual toggle, but also external group-sync and any group-membership edit that changes a manager set.

| Mutation | Server | Client invalidate |
|---|---|---|
| share / manage_access change | — | `['<resource>', id]` **and** list key `['<resource>s']` |
| **Make/Revoke Manager** — manual toggle (§5.4 `manage:M`, **KEPT** `3d994d5`) | `recompute_user_permissions(target)` | `['me']` (target) + `['userGroups']` + `['userGroup', gid]` |
| **External group-sync flips manager status** (SCIM / OIDC / OAuth group sync) | `recompute_user_permissions(affected)` **in the sync task** | no client mutation fires → `['me']` refreshes on next poll (**staleness window**, below) |
| Group-membership add/remove that changes a manager set | `recompute_user_permissions(affected)` | same as make-manager |
| ownership transfer | — | `['<resource>', id]` + list key |
| create / delete | — | list key only |

**Reconciliation with §5.4.** The Make/Revoke Manager toggle is the per-group `manage` affordance (`permissions.manage`, M) and its UI commit `3d994d5` is **KEPT** (§6.4) — it is the only path that reaches PR5's `PUT …/manager` route, so this row is a live mutation, consistent with §5.4.

**Staleness window (documented, accepted).** External group-sync runs in a background worker with no client `onSuccess`, so `['me']` is not busted synchronously — a newly-promoted/demoted manager sees stale nav/buttons until the next `/me` refetch (React Query `staleTime` / refetch-on-focus). This is **least-astonishment, not security**: the PEP still fail-closes, so a stale-*shown* button 403s and a stale-*hidden* button self-heals on refetch. Bound it with a short `staleTime` on `['me']` (or refetch-on-focus); tightening it to push-invalidation is a §6.6 tuning knob.

### 6.4 Rollout

- Fresh branch `Subash-Mohan/perms-pr6-manager-ui-v2` off **PR5** (`perms-pr5-manager-assignment-membership`). Leave PR6-v1 (`perms-pr6-manager-ui-scoped-nav`, **7 commits**) on origin as reference — do not force-push over it.
- **Revert scope** = only the two commits that reveal nav / hide affordances client-side. The backend `/me` + group-snapshot additions **and the Make/Revoke Manager UI** stay — the new model builds on them.

| PR6-v1 commit | Disposition | Why |
|---|---|---|
| `8de63e1` expose manager status on `/me` + group snapshot (`is_group_manager`, `manager_ids`) | **KEEP** | clean — backend models + FE types the v2 Layer-1/per-group signal builds on |
| `e3532e5` log exception on failed manager assignment | **KEEP** | bundled with `3d994d5` — its log line lives *inside* that function |
| `3d994d5` Make/Revoke Manager toggle on group edit | **KEEP** | **reverting it deletes the ONLY UI to assign a manager → PR5's `PUT …/manager` route is unreachable → nobody becomes a manager → whole feature inert.** It is an orthogonal member-table UI, independent of the nav/`visibilityPermissions` revert; gated by §5.4 `permissions.manage` (M) |
| `dc58897` reveal scoped admin nav for managers | **REVERT** | replaced by `admin_capabilities`-sourced nav (§4.3) |
| `0e3fb24` hide admin-only group affordances | **REVERT** | replaced by per-item `permissions{}` (§5.4) |
| `8fa5a18` gate org-wide agent actions on global perm | **SUPERSEDE** | correct-tier idea, re-expressed as `feature/list/delete = A` in the map (§3.3) |
| `0d4aea6` e2e for assignment & scoped nav | **REWRITE** | as the §6.1 E2E whole-surface invariant |

**Roll-up:** KEEP 3 (`8de63e1`, `e3532e5`, `3d994d5` — 2 backend + the make-manager UI); REVERT 2 (`dc58897` nav reveal, `0e3fb24` hide-affordances); SUPERSEDE 1 (`8fa5a18`, folded into the map vocabulary); REWRITE 1 e2e (`0d4aea6`). *(SHAs corrected: `dc59882`→`dc58897`, `0e3f240`→`0e3fb24`.)*

### 6.5 PR roadmap (5 review-sized PRs, drift checkpoint each)

Re-estimated honestly: the D1 shared-helper extraction + the real contract harness + the D4 route-coverage test add scope the v1 sizing understated, so the spine splits into a backend and a frontend PR to stay review-sized. The make-manager toggle is **KEPT** (no rebuild). Per-resource `can_*` wrappers + hand-written action unions + the required `permissions` field land **with the resource that uses them**, not up front.

| PR | Scope | LOC | Drift checkpoint |
|---|---|---|---|
| **A1 — Backend spine + shared helper + harness** | `admin_capabilities` on `/me`; **Tier-0 extraction** `within_scope`/`manages_group` from `assert_within_scope`/`assert_manages_group` (behavior-preserving); the **real contract harness** (`test_helper_matches_guard`) + **route-coverage test** (D4); **connectors** `permissions` map as proof (`can_edit_cc_pair` = existing `is_editable_for_current_user`, `cc_pair.py:326`). | ~650 | **PR1–5 enforcement suite green** (proves security byte-for-byte unchanged after extraction); helper-parity green for `cc_pair`; route-coverage green with connectors registered. |
| **A2 — Frontend spine** | `<Can>` / `can()` + `useCapabilities()`; hand-written per-resource action unions + **required** `permissions` DTO type (D4); **per-page default-deny gate** in `AdminSSChrome` — unmatched `/admin/*` requires `FULL_ADMIN_PANEL_ACCESS` (D5) + enumerate the missing routes (`systeminfo`, `groups2`, `federated/[id]`) in `ADMIN_ROUTES`; add `MANAGE_SKILLS`/`MANAGE_ACTIONS` to the FE `Permission` enum + `ADMIN_ROUTES` (D4); **delete** `visibilityPermissions`/`SCOPED_MANAGER_PERMISSIONS`; connectors client cutover. | ~550 | grep proves **0** `visibilityPermissions`/`SCOPED_MANAGER_PERMISSIONS` sites in web; an unmapped `/admin/*` path redirects (fails closed); nav re-sourced from `admin_capabilities`. |
| **B — Agents + Doc sets** | extract `can_edit_persona` (editable ∧ scope), `can_share_persona`, `can_view_persona_stats` (O, `analytics.py:339`), `can_delete_persona`/`can_publish_persona` (O\|A); stamp on the **per-card `GET /persona/{id}`** (D3 — never the hot chat/explore list); replace `checkUserOwnsAgent` as a gate → `<Can>` (kept only as the "Your Agents" *label*); dedupe the 3 wrong `canUpdateFeaturedStatus` copies; `DocumentSetSummary.permissions` (kills the double-fetch/set-diff). | ~700 | helper-parity green for `persona`(edit/share/view_stats/delete/publish) + `document_set`; AgentCard renders identically for owner vs in-scope editor; `view_stats` stamps `false` for an out-of-scope manager (O ≠ M). |
| **C — Skills + Actions/MCP + Tools** | `CustomSkillResponse.permissions`; extract `can_edit_custom_tool` (**M\|O** — admin ∨ creator `user_id` ∨ scoped, `tool/api.py:84,100`) and `can_edit_mcp_server` (**M\|O** — admin ∨ owner-by-**email** ∨ scoped, `mcp/api.py:1376,1386`); tools/MCP have **no `get_editable` list filter** → stamp `edit` only on the **detail/edit fetch** or via a batch resolver, not the list (D3). | ~650 | helper-parity green for `skill`/`mcp_server`/`tool`; **owner/creator sees `edit` on their own resource** (M\|O), manager out-of-scope does not; MCP owner-by-email cell asserted. |
| **D — Groups + Token limits + Federated + closing gate** | `UserGroup.permissions` incl. **per-group `manage:M`** via `can_manage_group` (`manages_group`, single-group); token-rate-limit map (POST=scoped M, PUT/DELETE/GET=A); **federated connectors** gated on `isAdmin`/global `MANAGE_CONNECTORS`, `/admin/federated` enumerated FULL_ADMIN (D6); land the **full** parametrized matrix + E2E as the closing gate. | ~550 | **full** matrix green (5 actors × 7 resources); per-group `manage` asserted; federated affordance no longer 403s a manager; E2E "manager sees exactly in-scope" passes; route-coverage covers *all* mutating scoped routes. |

Each checkpoint = the contract harness extended to that PR's resources passes before merge; PR-D's is the complete matrix, so drift cannot survive the final merge. Admin-list stamping preloads the editable-id **set** once and stamps each row from memory (connectors template) with `managed_group_ids: set[int]` on the ctx dataclass so per-row stamping does **no** DB (D3).

### 6.6 Open decisions

Federated affordances (D6), the `ResourceAction` codegen (D4), and the `can()` consolidation (D1) are **no longer open** — they moved into the design (see "Resolved," below). What remains genuinely open:

| # | Decision | Options / lean |
|---|---|---|
| 1 | **`POST /capabilities` in v1 vs fold into `/me`** | v1: `admin_capabilities` on `/me` covers all Layer-1 needs (small, static per session). A batch endpoint only pays off for large per-item capability fan-out. *Lean: ship on `/me`; add `POST /capabilities` (AuthZEN-style advisory batch) as a deferred appendix only if a screen needs per-item Layer-1 checks at scale.* |
| 2 | **`['me']` staleness bound on external group-sync** (D8) | The sync task recomputes server-side, but no client mutation busts `['me']`, so a promoted/demoted manager sees stale nav until refetch. *Lean: short `staleTime` + refetch-on-focus on `['me']` (fail-closed already covers correctness); upgrade to push/websocket invalidation only if the window proves annoying.* |
| 3 | **Stamp O-class MCP admin actions now vs defer** | `delete`/`authenticate`/`manage_status` are owner-or-admin (`_ensure_mcp_server_owner_or_admin`, `mcp/api.py:1358`). *Lean: extract a sibling `can_admin_mcp_server` and stamp them in PR-C alongside `edit`; trivial once the M\|O `edit` helper exists.* |

**Resolved since v1 (folded into the design):**
- **Federated connectors** (was open #1) → gate on `isAdmin`/global `MANAGE_CONNECTORS`; `/admin/federated` enumerated FULL_ADMIN (§5.6, D6). No scoped model in v1.
- **`ResourceAction` union** → hand-written per-resource unions + **required** `permissions` field + route-coverage test (§4.5/§6.1, D4). No codegen dependency.
- **`can()` facade** (was open #3) → **promoted to a required v1 core**: `can_<action>` is the shared decision helper that makes `project == enforce` by construction (§3.1a, D1). It is an internal server function, not an HTTP endpoint.