> Status: draft → active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — Spec Index

Implementation spec for **§8** of the Group-Based Permissions System V2. The base system (§1–7) is built on
`new-permission-system`; §8 is the one remaining, fully-greenfield section.

Source of truth (wiki): `Engineering Projects/Group-Based Permissions System V2/solution-design.md` §8.

| # | Doc | Contents | Status |
|---|---|---|---|
| 01 | [01-research.md](01-research.md) | Requirement · codebase verification (§8 absent / §1–7 built) · industry backing · locked wiki §8 approach + carried-in must-fixes · migration trap | ✅ |
| 02 | [02-high-level-design.md](02-high-level-design.md) | Plain-language whole-approach: two-gate model, live scope, data flow, scenario, decisions that matter | ✅ |
| 03 | [03-detailed-design.md](03-detailed-design.md) | DB design (+rationale) · auth primitives · ~4 filter rewrites (+skill, +token-limit; §11) · write-path gate insertions · PAT · API · FE · file tree · pre-impl notes · open decisions | ✅ |
| 04 | [04-implementation-plan.md](04-implementation-plan.md) | CLAUDE.md-format plan + plan-challenge results (passed all 6) | ✅ |
| 05 | [05-pr-roadmap.md](05-pr-roadmap.md) | 6 ordered PRs (~2.3k LOC) w/ drift checkpoints + lands-together safety invariant | ✅ |
| 07 | [07-ui-capability-model-design.md](07-ui-capability-model-design.md) | **UI redesign** (server-driven capability model): kills client-side `visibilityPermissions()`; `/me.admin_capabilities` (coarse) + per-resource `permissions{}` map (per-item) stamped by a shared `can_<action>` helper the write-guard also calls (drift impossible by construction); `<Can>` primitive; 49/109 affordance audit + complete mapping + real contract test + 5-PR roadmap. **v2** — revised after a 34-finding adversarial pressure test | 🆕 design (v2) |
| 10 | [10-branch-audit-anon-and-service-accounts.md](10-branch-audit-anon-and-service-accounts.md) | Independent branch audit: anonymous-access regression check (none found) · groupless-service-account behavior spec · **CRITICAL live-confirmed escalation** (GLOBAL `manage:user_groups` holder can self-add to the Admin default group) · 31 more ranked findings | ✅ audit |

**Decisions locked at GATE 2:** D1 cache `is_group_manager` boolean (route gate zero-query; managed-list stays
live) · D2 admins-only create groups · D3 admin-or-manager-of-that-group assigns managers.

**Decisions locked at the 2026-06-29 regression + GO/NO-GO reviews:** D4 actions = `manage:actions`
**stays in the bundle** (GATE 1 reach), scoped via the agents that reference them at GATE 2 · D5 skills = a 7th scoped resource under a **new dedicated
`manage:skills` permission** (grantable in the groups UI + in the bundle; no DB migration) · D6 managers may do
everything **except delete** · **D7 attaching an agent to a group is controlled by `manage:agents`** (standard GATE 2 keyed on
`MANAGE_AGENTS` — admins/global holders self-share to their groups, scoped managers to managed groups;
`add:agents`-only users can't group-share). The reviews confirmed PAT,
chat-runtime, and document/Vespa ACL are untouched, and refuted the backfill data-loss concern. Full
case-by-case coverage + the boot-bug prerequisite are in **[03 §11](03-detailed-design.md)** — the
authoritative implementation checklist.

**Decision locked 2026-08-03:** **D8 action + MCP-server _management_ (edit / toggle / OAuth-auth) is
owner-or-admin, NOT agent-mediated.** D4 still holds for GATE 1 reach + create (a scoped manager reaches
the action/MCP routes and may create), but the agent-mediated GATE 2 that once let a manager edit any
action whose referencing agents were all in their managed groups was **dropped** — it was the source of
most of the review's P1/P2 findings, and the simpler owner-or-creator gate (`can_manage_own_tool` /
`_ensure_mcp_server_owner_or_admin`, mirrored 1:1 by the UI projection) is the intended final design. Delete
follows D9 below. This **supersedes** the "agent-mediated GATE 2 replaces owner-or-admin" language
still in [03 §11](03-detailed-design.md), [05](05-pr-roadmap.md), and [07](07-ui-capability-model-design.md).

**Decision locked 2026-08-04:** **D9 delete/publish follow ownership — D6's "except delete" scopes
managed-group resources, not ones the manager created.** A scoped manager may delete a custom action or
MCP server *they created*, and publish an agent *they own*, exactly as any other owner may: the gate is
owner-or-admin (`can_manage_own_tool`, `_ensure_mcp_server_owner_or_admin`, `can_delete_persona`), and
being a manager never subtracts a right they'd hold as an ordinary user. D6 still holds where it was
aimed — a manager may not delete a connector, document set, or agent that merely sits in a group they
manage. Pinned by `test_permission_projection_contract.py` ("the creator fully controls the action they
made"); `assert_within_scope` in `_assert_persona_update_within_managed_scope` therefore does **not**
gate `is_public`, and the EE group-share gate exempts an owner whose group shares are unchanged —
**shares, not just group ids**: re-leveling a group from VIEWER to EDITOR is a change and gets no
exemption. What ownership never buys is *widening* — sharing a public agent into a managed group still
rejects, because that would capture it into scope.
