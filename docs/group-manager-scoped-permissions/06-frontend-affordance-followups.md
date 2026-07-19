> Status: follow-up · Task: group-manager-scoped-permissions · Depends on: PR6 (manager UI & scoped nav)

# Frontend affordance follow-ups (group managers)

PR6 reveals the scoped admin nav to group managers and treats them as holding the
scoped `manage:*` tokens (via `visibilityPermissions`, exposed as
`useUser().permissions`). That is correct for **coarse** decisions (nav, page
access, "New X", scoped create/edit). Two gaps remain for **fine-grained**
affordances. This doc captures them so they can be picked up independently.

## The model (already encoded in `web/src/lib/permissions.ts`)

A flat permission token answers "can you do X **at all**?" — it cannot answer "can
you do X **to this specific resource**?". So the UI has three gate kinds:

| Decision | Gate | Managers |
|---|---|---|
| Coarse: nav, page access, "New X", scoped create/edit | `hasPermission(permissions, X)` | included (they hold X, scoped) |
| Global / org-wide action (feature, publish org-wide, delete) | raw `user.effective_permissions` (or `isAdmin` if FULL_ADMIN-gated) | excluded |
| Action on a specific item in a **read-scoped** list | that item's backend editable flag | per-item |

None of this is a security boundary — the backend enforces scope on every request
(GATE 2). This is purely to avoid advertising controls that will 403.

---

## Follow-up 1 — `is_editable` on the agent snapshot (the main gap)

**Problem.** On read-scoped surfaces (chiefly the chat-page agent list, which shows
agents a user can *use*, not only ones they can edit), per-agent edit affordances
currently key off ownership. A group manager can edit agents **shared to a group
they manage** even though they do not *own* them, so an ownership check wrongly
**hides** those actions. A capability check (`hasPermission(permissions,
MANAGE_AGENTS)`) would wrongly **show** the action on *every* agent, including
public/other-group agents (advertises a 403). Neither signal is right; only
per-agent "can I edit this one?" is.

**Why only agents.** Agents are the one resource that appears in a read-scoped list
*with* edit affordances. Admin list pages are already backend-scoped (the list
returns only editable-for-you rows via the `get_editable=True` persona filter), so
they need no per-item flag. Other resources don't surface edit controls in read
lists. So this is **not** "add `is_editable` to every resource" — just the agent
snapshot.

**Backend.** Add `is_editable: bool` to `PersonaSnapshot`
(`backend/onyx/server/features/persona/models.py`), computed for the requesting
user. Reuse the existing editable-scope logic rather than re-deriving it — e.g. in
the list endpoint(s) that build snapshots, resolve the editable persona-id set once
(the same `_add_user_filters(get_editable=True)` predicate) and mark each snapshot
`is_editable = id in editable_ids`. This keeps owner / admin / scoped-manager /
group-shared all consistent with GATE 2 (single source of truth).

**Frontend.** In `AgentRowActions` and any chat-page agent control, gate the
edit/manage affordances on `agent.is_editable` instead of ownership/capability.
Keep the **feature** toggle on the global check (`user.effective_permissions`
holds `MANAGE_AGENTS`) — featuring is org-wide, not a per-agent edit.

**Test.** Integration/e2e: a manager sees edit actions on an agent shared to a
managed group, and does **not** see them on a public agent or one shared only to an
unmanaged group.

---

## Follow-up 2 — audit remaining global-action gates

PR6 fixed the flagged case: `AgentRowActions.canUpdateFeaturedStatus` now uses raw
`user.effective_permissions` (featuring is a global `MANAGE_AGENTS` action the
backend gates without `allow_scope`), so a scoped manager no longer sees it.

Sweep the other `hasPermission(permissions, MANAGE_*)` call sites and classify each:

- `web/src/components/IsPublicGroupSelector.tsx` — "make public" is org-wide → raw.
- `web/src/app/admin/documents/sets/DocumentSetCreationForm.tsx` — group selection
  is scoped (keep); any "public" toggle is global → raw.
- `web/src/sections/agents/AgentCard.tsx`, `ShareAgentModal.tsx`,
  `refresh-components/popovers/ActionsPopover/*`, `AgentsNavigationPage.tsx`,
  `admin/connector/[ccPairId]/page.tsx` — classify per action.

Rule: an org-wide action → raw `effective_permissions` / `isAdmin`; a scoped
create/edit → `hasPermission(permissions, X)` (managers included).

---

## Follow-up 3 — admin read endpoints without `allow_scope`

PR6 nav can reveal an admin page whose **read/list** endpoint still requires the
GLOBAL token, so a scoped manager 403s on load (e.g.
`get_agents_admin_paginated` / `list_personas_admin` are gated `READ_AGENTS` with no
`allow_scope`). Confirm each manager-visible admin list endpoint admits scoped
managers (`allow_scope=True` + a scoped read filter, as PR3 did for connectors /
doc sets) so the revealed pages actually load. This is backend work in the PR3/PR4
family, tracked here only because PR6 surfaces the pages.
