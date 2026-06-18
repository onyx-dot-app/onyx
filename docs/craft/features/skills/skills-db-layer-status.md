# Skills — DB Layer Status

Status snapshot of what's already implemented on branch `whuang/skills-api`. This is the foundation the API layer (next phase) builds on.

## TL;DR

The DB layer ships **two tables**, a **CRUD module**, an **Alembic migration**, an **in-memory built-in registry**, and a **synchronous bundle validator**. No HTTP routes yet — the API layer wires these primitives into FastAPI.

## 1. Tables

Both defined in `backend/onyx/db/models.py` (lines ~4176–4364) and created by migration `backend/alembic/versions/b6d184cfdaf3_skills.py`.

### `skill`
Per-tenant row representing a custom (admin-uploaded) skill.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `slug` | String(64) | unique (`uq_skill_slug`); URL-safe identifier |
| `name` | String | admin-editable |
| `description` | Text | admin-editable |
| `bundle_file_id` | String | reference to a blob in FileStore |
| `bundle_sha256` | String(64) | content hash of the raw zip |
| `author_user_id` | UUID? | FK → `user.id`, `ON DELETE SET NULL` |
| `is_public` | Boolean | org-wide visibility toggle (default `false`) |
| `enabled` | Boolean | admin soft-disable without delete (default `true`) |
| `created_at` / `updated_at` | TimestampTZ | server-managed |

**Not present:** `deleted_at` (soft-delete was deliberately dropped in `b8d0bb0414`), `manifest_metadata` (dropped in `9db09cc2d2`).

### `skill__user_group`
Junction table for group-based access grants.

| Column | Type | Notes |
|---|---|---|
| `skill_id` | UUID | FK → `skill.id`, `ON DELETE CASCADE`, part of composite PK |
| `user_group_id` | Integer | FK → `user_group.id`, `ON DELETE CASCADE`, part of composite PK |

No direct user-grant table exists (deferred).

## 2. CRUD Module — `backend/onyx/db/skill.py`

All functions flush but do **not** commit; callers control transaction boundaries.

### Reads
- `list_skills_for_user(user, db_session) -> Sequence[Skill]` — visibility-filtered, `enabled=True` only.
- `fetch_skill_for_user(skill_id, user, db_session) -> Skill | None`
- `list_skills_for_admin(db_session) -> Sequence[Skill]` — unrestricted.
- `fetch_skill_for_admin(skill_id, db_session) -> Skill | None` — includes disabled skills.
- `get_group_ids_for_skill(skill_id, db_session) -> list[int]` — returns granted group IDs for a skill.

### Writes
- `create_skill(slug, name, description, bundle_file_id, bundle_sha256, is_public, author_user_id, db_session) -> Skill` — pre-checks slug, converts `IntegrityError` into `OnyxError(DUPLICATE_RESOURCE)`.
- `patch_skill(skill_id, patch=SkillPatch, db_session) -> Skill` — accepts a `SkillPatch` frozen dataclass; uses `UNSET` sentinels so `None` is distinguishable from "not provided".
- `replace_skill_bundle(skill_id, new_bundle_file_id, new_bundle_sha256, db_session) -> tuple[Skill, old_bundle_file_id]` — caller deletes the old blob after commit.
- `replace_skill_grants(skill_id, group_ids, db_session) -> None` — atomic delete-and-insert; deduplicates.
- `delete_skill(skill_id, db_session) -> str | None` — hard-delete; returns `bundle_file_id` for post-commit blob cleanup; idempotent.

### Affected users
- `affected_users_for_skill(skill, db_session) -> set[UUID]` — returns user IDs with an active sandbox who should have this skill.

### Visibility filter
`_add_user_visibility_filter()` enforces `is_public OR user is in a granted group`, mirroring the persona visibility pattern.

## 3. Built-in Registry — `backend/onyx/skills/registry.py`

In-memory, process-wide singleton populated at app boot. Not DB-backed (built-ins are code artifacts).

Key types:
- `BuiltinSkill` — standalone `BaseModel` with `source = "builtin"`, `slug`, `name`, `description`, `source_dir: Path`, `has_template: bool`, `is_available: Callable[[Session], bool]`, `unavailable_reason: str | None`. Has its own slug validator.
- `BuiltinSkillRegistry` — `register()`, `list_all()`, `list_available(db)`, `get(slug)`, `reserved_slugs()`, plus `_reset_for_testing()`.

There is no `Skill` base class or `CustomSkill` domain model in the registry. Custom skills are represented solely by the ORM `Skill` model (in `db/models.py`) and the `CustomSkillResponse` Pydantic model (in `server/features/skill/models.py`). The DB CRUD module returns ORM `Skill` objects directly.

`register()` parses YAML frontmatter from `SKILL.md` or `SKILL.md.template` to populate `name` and `description`. Slug regex enforced; duplicate registration raises.

## 4. Bundle Validator — `backend/onyx/skills/bundle.py`

Synchronous (sub-second) validator for custom uploads. Exposes:
- `validate_custom_bundle(zip_bytes, slug) -> ManifestMetadata` — well-formedness, `SKILL.md` present, no `*.template`, no path traversal/symlinks, per-file ≤ 25 MiB, total ≤ 100 MiB.
- `compute_bundle_sha256(zip_bytes) -> str`
- Helpers for safe unzip used by future materializers.

The API layer calls these before writing to FileStore.

## 5. Migration

`alembic/versions/b6d184cfdaf3_skills.py` (prev `37b5864e9cff`):
- Creates `skill` and `skill__user_group`.
- One unique constraint (`uq_skill_slug`); no additional indexes in V1.
- No data migration.

## 6. Related Touch-points

- `FileOrigin.SKILL_BUNDLE` added to `configs/constants.py` for tagging custom bundle blobs in FileStore.
- No persona/tool/chat models reference the skill tables — skills are a standalone primitive in V1.

## 7. Known Gaps

The DB layer is sufficient for V1 of the API. Known gaps the API layer either consumes or defers:

1. **No HTTP surface** — no router exists for skills yet. This is the next phase.
2. **No automatic blob cleanup** — `delete_skill` and `replace_skill_bundle` return the orphaned `bundle_file_id` and the caller must clean up. A periodic sweep job is deferred.
3. **No soft-delete** — `DELETE` is destructive. Slug reuse works because the row is gone.
4. **No direct user grants** — only group grants exist. Deferred to a later phase.
5. **No query indexes beyond PK + unique slug** — fine at current scale.
6. **No built-ins registered yet** — registry exists, but the V1 set (pptx, image-generation, bio-builder, company-search) hasn't been wired in.

## 8. Branch Commits (for traceability)

In chronological order on `whuang/skills-api`:
1. `b91f2d1450` — V1 foundation schema (models + migration + module skeletons).
2. `b8d0bb0414` — simplified slug uniqueness (dropped soft-delete + partial index).
3. `44eb6ecab6` — built-in registry primitive + bundle validator + CRUD module + unit tests.
4. `9db09cc2d2` — dropped stale `manifest_metadata` references.
