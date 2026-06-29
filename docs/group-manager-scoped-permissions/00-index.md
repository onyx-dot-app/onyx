> Status: draft → active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — Spec Index

Implementation spec for **§8** of the Group-Based Permissions System V2. The base system (§1–7) is built on
`new-permission-system`; §8 is the one remaining, fully-greenfield section.

Source of truth (wiki): `Engineering Projects/Group-Based Permissions System V2/solution-design.md` §8.

| # | Doc | Contents | Status |
|---|---|---|---|
| 01 | [01-research.md](01-research.md) | Requirement · codebase verification (§8 absent / §1–7 built) · industry backing · locked wiki §8 approach + carried-in must-fixes · migration trap | ✅ |
| 02 | [02-high-level-design.md](02-high-level-design.md) | Plain-language whole-approach: two-gate model, live scope, data flow, scenario, decisions that matter | ✅ |
| 03 | [03-detailed-design.md](03-detailed-design.md) | DB design (+rationale) · auth primitives · 6 filter rewrites · write-path gate insertions · PAT · API · FE · file tree · pre-impl notes · open decisions | ✅ |
| 04 | [04-implementation-plan.md](04-implementation-plan.md) | CLAUDE.md-format plan + plan-challenge results (passed all 6) | ✅ |
| 05 | [05-pr-roadmap.md](05-pr-roadmap.md) | 6 ordered PRs (~2.3k LOC) w/ drift checkpoints + lands-together safety invariant | ✅ |

**Decisions locked at GATE 2:** D1 cache `is_group_manager` boolean (route gate zero-query; managed-list stays
live) · D2 admins-only create groups · D3 admin-or-manager-of-that-group assigns managers.
