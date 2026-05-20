# Skills — Requirements

Clean restatement of the V1 requirements distilled from `skills.md`, `skills_plan.md`, `TODOS.md`, and decisions made on branch `whuang/skills-api`. This supersedes those longer documents for the purpose of planning the API layer.

## 1. Concept

A **skill** is a self-contained bundle of agent-facing instructions (a `SKILL.md` plus optional scripts and supporting docs) that teaches an agent how to perform a category of task. Skills surface to a running sandbox as a directory the agent can read with `ls` and `cat`.

Two flavors:

| Flavor | Origin | Storage | Lifecycle |
|---|---|---|---|
| **Built-in** | Ships in the codebase under `docker/skills/<slug>/` | Source files on disk + in-memory registry entry | Deployed with the app; no per-tenant config |
| **Custom** | Uploaded as a zip by a tenant admin | `skill` row in Postgres + bundle blob in object storage | Mutable per tenant; admin-managed |

Both follow the same on-disk format and are indistinguishable to the agent at run time.

## 2. Bundle Format

```
<slug>/
├── SKILL.md             # required; YAML frontmatter with `name` and `description`
├── scripts/             # optional
└── *.md                 # optional supporting docs
```

Built-ins may use `SKILL.md.template` with `{{placeholder}}` substitutions; customs may not (templating reserved for built-ins).

Validation rules for custom uploads (already implemented in `backend/onyx/skills/bundle.py`):
- Well-formed zip
- `SKILL.md` present at root
- No `*.template` files
- No path traversal, no symlinks
- Per-file ≤ 25 MiB, total ≤ 100 MiB
- Slug matches `^[a-z][a-z0-9-]{0,63}$`
- Slug not already used by an active custom skill
- Slug not in the built-in reserved set

## 3. Data Model

Already implemented; see `skills-db-layer-status.md` for column-level detail.

- `skill` — per-tenant row holding metadata, `bundle_file_id`, `bundle_sha256`, `is_public`, `enabled`, author.
- `skill__user_group` — junction for group-based grants.
- Built-ins are **not** rows in Postgres; they're registered at app boot in `BuiltinSkillRegistry`.

## 4. Visibility & Permissions

### Custom skills
- `is_public = true` → visible to every user in the tenant.
- `is_public = false` → visible to users in any granted user group (via `skill__user_group`).
- `enabled = false` → invisible to users; still visible to admins (for re-enable).
- Hard-deleted skills disappear (no soft delete in V1).

### Built-in skills
- No per-tenant control row.
- Each built-in declares an `is_available(db_session) -> bool` callable. If it returns `false`, the skill is silently hidden from users for that tenant.
- Admins can see availability status and reason (e.g., "Needs setup") but cannot toggle availability.

### API auth
- Admin endpoints require curator/admin (matching the persona admin router).
- User endpoints require basic-access permission.

## 5. Sandbox Delivery

Skills delivery uses `SandboxManager`'s push API documented in `../sandbox-file-push.md`. Skills builds bytes and calls; the push methods own the wire protocol, NetworkPolicy, shared secret, fan-out, and atomic swap.

- **Admin mutations** (custom upload, bundle replace, grant change, `is_public` flip, builtin availability flip): the skills feature computes the set of affected users, queries the DB for their sandbox_ids, builds a sandbox_id-to-files mapping, and calls `get_sandbox_manager().push_to_sandboxes(mount_path="/workspace/managed/skills", sandbox_files=...)`. A single-user grant change produces a one-entry mapping; an org-wide change (e.g. `is_public=True`) spans every affected sandbox in the tenant.
- **Session start / wakeup**: the existing sandbox setup code calls `skills.push_to_pod(sandbox_id, user, db_session)`, which materializes the user's accessible skill set and pushes via `get_sandbox_manager().push_to_sandbox(...)`.
- **Mount path** inside the sandbox is `/workspace/managed/skills/<slug>/`. The agent reads from there.
- **Per-user templating**: built-in `SKILL.md.template` files are rendered against the target user's `SkillRenderContext` at materialization time, which fits naturally into the per-user push model.
- Users without an active sandbox are silently skipped by the push API.

## 6. API Surface (target for this phase)

### Admin (`/admin/skills`)
- `GET /admin/skills` — list all skills the admin can manage (built-ins with availability metadata + customs with grants).
- `POST /admin/skills/custom` — upload a new custom skill (multipart: bundle + slug + name + description + flags).
- `PATCH /admin/skills/custom/{id}` — edit slug, name, description, `is_public`, `enabled`.
- `PUT /admin/skills/custom/{id}/bundle` — replace bundle bytes.
- `PUT /admin/skills/custom/{id}/grants` — atomic replace of group grants.
- `DELETE /admin/skills/custom/{id}` — hard-delete.

### User (`/skills`)
- `GET /skills` — list skills the current user has access to (available built-ins + accessible customs).
- `GET /skills/{slug_or_id}` — fetch metadata for a single skill (optional in V1; useful for UI previews).

No per-session "pin a skill" endpoints. No in-browser skill editor. No skill execution endpoints (skills run inside the sandbox via the agent, not via Onyx APIs).

## 7. Multi-Tenancy

- Custom skills, slug uniqueness, and grants are tenant-scoped (existing schema/middleware semantics).
- Built-in skills are shared across tenants; `is_available()` may inspect tenant config but the registration is global.
- Cross-tenant isolation at push time is the skills code's responsibility: it queries tenant-scoped DB tables for sandbox_ids (the existing schema/middleware ensure tenant isolation in DB queries), then passes those sandbox_ids to `SandboxManager.push_to_sandboxes`. The push API itself has no tenant concept.

## 8. Non-Requirements (V1)

These are explicitly out of scope and should not be designed into the API:

- Versioning (re-upload replaces the bundle in place).
- Per-session pinning or selection UI.
- In-browser skill editing.
- Marketplace, sharing across tenants, or signed bundles.
- Per-skill secrets/configuration (handled in a separate "interception" layer).
- Direct user grants (only group grants in V1).
- Skill telemetry / per-skill usage metrics.
- Skill-to-skill dependencies.
- Automatic orphan-blob cleanup (callers handle cleanup; a periodic sweep is deferred).

## 9. Open Questions

- **Org-wide fan-out cost.** A public-skill mutation in a large tenant materializes per-user bundles for every user with an active sandbox. The push API caps total bundle size at 100 MiB, but the skills-side cost of rebuilding the dict for hundreds of users is unmeasured. Acceptable for v1; revisit if it shows up in admin-mutation latency.
