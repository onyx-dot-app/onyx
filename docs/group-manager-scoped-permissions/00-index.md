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

**Decisions locked at GATE 2:** D1 cache `is_group_manager` boolean (route gate zero-query; managed-list stays
live) · D2 admins-only create groups · D3 admin-or-manager-of-that-group assigns managers.

**Decisions locked at the 2026-06-29 regression + GO/NO-GO reviews:** D4 actions = agent-mediated
(`manage:actions` dropped from the bundle) · D5 skills = a 7th scoped resource under a **new dedicated
`manage:skills` permission** (grantable in the groups UI + in the bundle; no DB migration) · D6 managers may do
everything **except delete** · **D7 attaching an agent to a group is controlled by `manage:agents`** (standard GATE 2 keyed on
`MANAGE_AGENTS` — admins/global holders self-share to their groups, scoped managers to managed groups;
`add:agents`-only users can't group-share). The reviews confirmed PAT,
chat-runtime, and document/Vespa ACL are untouched, and refuted the backfill data-loss concern. Full
case-by-case coverage + the boot-bug prerequisite are in **[03 §11](03-detailed-design.md)** — the
authoritative implementation checklist.
