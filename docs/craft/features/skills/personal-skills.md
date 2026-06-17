# Skills — Personal (User-Managed) Skills

Status snapshot for the `user-skills` branch (PR #11923). This documents the
personal-skills slice built on top of the already-shipped admin skills feature
(`skills-requirements.md`, `skills-db-layer-status.md`, `skills-api-plan.md`).
Read those first for the underlying data model and the admin/built-in surface.

## TL;DR

Admin skills let an **admin** upload a zip bundle and grant it org-wide or to
groups. **Personal skills** extend the *same* `skill` table so a **basic user**
can self-serve: upload, replace, enable/disable, and delete their own skill
bundles, visible only to themselves. Admins keep oversight on the
`/admin/skills` surface — they can **promote** a personal skill org-wide or
**hard-delete** it. There is **no new table** and **no new column dedicated to
"personal"**; personal-ness is a *derived* property of an existing row.

## 1. Core concept: "personal" is derived, not stored

A row is a **personal skill of user U** when all of these hold (see
`_personal_skill_clause` in `backend/onyx/db/skill.py`):

- `built_in_skill_id IS NULL` (it's a custom, not a built-in)
- `is_public = false`
- zero rows in `skill__user_group` (no group grants)
- `author_user_id = U`

This is deliberate and **fully reversible by admins** — "personal" is a view of
the row's current state, not a stored mode. A personal skill becomes
"org-managed" the instant an admin makes it public **or** adds a group grant,
and the owner loses self-serve control while it stays that way. If an admin
later clears `is_public` and removes every group grant via the normal admin
visibility controls, the row again satisfies the predicate and the original
author regains self-serve access — that is intended (it is once more a private,
author-owned custom skill), not an invariant violation. There is intentionally
no persisted "promoted" flag to make promotion one-way.

`_personal_skill_clause` is the **single source of truth** for this predicate.
It is shared by:

- the user visibility filter (`_add_user_visibility_filter`),
- the sandbox-injection fanout (`affected_user_ids_for_skill`),
- the per-user cap counter (`count_personal_skills_for_user`),

so the three can't drift. If you change what "personal" means, change it here
only.

## 2. API surface

New **user-facing** routes (prefix `/skills`, gated by `BASIC_ACCESS`), in
`backend/onyx/server/features/skill/api.py`:

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/skills/custom` | Create a personal skill from an uploaded bundle |
| `PUT` | `/skills/custom/{id}/bundle` | Replace the bundle (owner only) |
| `PATCH` | `/skills/custom/{id}` | Toggle `enabled` (owner only) |
| `DELETE`| `/skills/custom/{id}` | Hard-delete (owner only) |
| `GET` | `/skills` and `/skills/{slug_or_id}` | List/fetch (pre-existing, visibility-filtered) |

The **admin** routes (`/admin/skills/...`) are unchanged in shape but now also
operate on personal skills: `PATCH ... {is_public: true}` is the **promote**
action, and `DELETE` is the admin **hard kill switch** for any user's personal
skill.

### Ownership gating

Every user mutation route fetches the row with `fetch_skill_by_id` (a bare
primary-key fetch — **not** visibility-filtered) and then calls
`_ensure_owned_personal(skill, user, db_session)`:

- non-author → `404 NOT_FOUND` (don't reveal the row exists),
- author of a *promoted* skill → `403 INSUFFICIENT_PERMISSIONS` (org-managed now),
- built-in row → blocked by `_ensure_custom`.

**Why the bare fetch instead of `fetch_skill_for_user`?** An admin-disabled
personal skill must stay mutable by its owner. The user-scoped fetcher's intent
is *visibility*; ownership is a *separate* concern. Bare-fetch + explicit
ownership gate keeps the two from being conflated (this mirrors
`projects/api.py`, which filters `user_id` explicitly rather than reusing a
visibility query).

## 3. Per-user cap (race-free)

`MAX_PERSONAL_SKILLS_PER_USER` (default 50) lives in
`backend/onyx/configs/app_configs.py` and is env-overridable (CI lowers it so
the cap test doesn't upload 50 real bundles).

The check is **lock-then-count-then-insert**, all in one transaction:

```python
lock_personal_skills_for_user(user.id, db_session)   # pg_advisory_xact_lock
if count_personal_skills_for_user(user.id, db_session) >= MAX_...:
    raise OnyxError(...)
# ... create row, commit (releases the lock)
```

`lock_personal_skills_for_user` mirrors the established `acquire_seat_lock`
precedent in `ee/onyx/db/license.py`: hash the key (`sha256` of a namespaced
user id) to a signed 64-bit int and call single-arg `pg_advisory_xact_lock`.
Without the lock, two concurrent uploads from the same user could both pass the
count check and exceed the cap.

## 4. Sandbox delivery

Personal skills ride the same `SandboxManager` push model as admin skills.
`affected_user_ids_for_skill` computes which running sandboxes need a re-push on
create/enable/disable/delete. For a personal skill that set is "the author, if
they have a running sandbox." Mutation routes union before- and after-states
(`before_affected | after_affected`) so a toggle pushes the corrected fileset.

**Security note:** `_add_user_visibility_filter` gives admins **no bypass** — it
feeds sandbox injection, and a bypass would push every user's (untrusted)
personal skill into admins' agent contexts. Admin oversight is the
`/admin/skills` listing, not injection.

## 5. Slug rules

Slugs share **one namespace** across personal + admin + built-in skills:

- Reserved slugs (built-in ids + external-app provider slugs in
  `_RESERVED_SKILL_SLUGS`) are rejected at create time — a user-claimed slug
  would block the org from connecting that app.
- Duplicate slug (against *any* existing skill, personal or org-wide) →
  `409` via the `uq_skill_slug` unique constraint.

## 6. Frontend

- **User page** `web/src/refresh-pages/UserSkillsPage.tsx` — lists built-ins +
  the user's visible customs; "Create skill" opens
  `UserSkillsPage/CreatePersonalSkillModal.tsx`. Per-card replace/toggle/delete
  live on `web/src/sections/cards/SkillCard.tsx` and are gated by a `busy`
  prop / `pendingId` so a shared hidden file-input can't be retargeted and
  toggles can't race.
- **Admin page** `web/src/refresh-pages/admin/SkillsPage.tsx` — adds the
  **promote** action (only shown when `skill.is_personal`); confirm modal warns
  the author loses self-serve management. `promoteTarget` clears only on
  success so a failed promote keeps the dialog open.
- API client: `web/src/lib/skills/api.ts`
  (`createPersonalSkill`/`replaceUserSkillBundle`/`patchUserSkill`/`deleteUserSkill`).
- `is_personal` is sent by the backend; the frontend additionally guards
  `author_user_id === user.id` when rendering owner-only controls.

Frontend follows the Onyx rules: `@opal/components`, `@opal/icons`, design
tokens, `cn()`. The two intentional exceptions, both currently unavoidable: a
hidden raw `<input type="file">` (no Opal file input exists; driven by an Opal
`Button`) and `Modal` from `@/refresh-components` (no Opal equivalent yet).

## 7. Tests

`backend/tests/integration/tests/skills/test_skills_personal.py` (HTTP
boundary, no mocking) covers: visibility isolation, owner replace/delete,
non-owner 404, reserved/duplicate slugs, cross-tier slug collision (both
directions), promotion lockout (403), owner toggle, admin-disabled-but-owner-
deletable, admin hard-delete, and the per-user cap. The manager helpers live in
`backend/tests/integration/common_utils/managers/skill.py`.

## 8. Decisions worth preserving (for the next agent)

- **No `is_personal` column.** Keep it derived via `_personal_skill_clause`.
  Adding a stored flag would create a second source of truth that can diverge
  from `is_public`/grants state.
- **"Personal" is derived and reversible — do NOT add a persisted promoted
  flag.** If an admin reverts a skill to fully private (no public, no grants),
  the author regaining self-serve control is intended, not a bug. Reviewers
  flag this as a "reversible predicate" violation; it isn't — it's the
  confirmed design for custom-skill visibility.
- **Ownership ≠ visibility.** Don't "simplify" the user mutation routes to use
  `fetch_skill_for_user`; the disabled-but-owned case needs the bare fetch.
- **The advisory lock is load-bearing.** Don't drop it for a "simpler"
  count-then-insert; the cap is unenforced without it.

## 9. Open questions / future work

- **Bundle size & zip-bomb bounds for user uploads.** `_read_bundle_upload`
  caps the *compressed* read; confirm `ingest_skill_bundle` bounds the
  decompressed size now that the upload path is open to all users.
- **Sharing between users.** V1 has personal (self) and org-wide (admin); no
  user-to-user share. Group grants are admin-only.
- **Per-user storage quota** beyond the count cap (bytes, not just rows).
- **Demote / un-promote** UX, if requested.
