# Skills V1 — PRD & Implementation Spec

**Status**: design · **Source plan**: `docs/craft/features/skills.md` · **Owner**: Roshan

This document is structured so implementation can begin section-by-section with minimal further design. Each section follows the same shape:

1. **Context** — what is the ask, why does it exist, what problem does it solve.
2. **Proposed Solution** — the V1 design.
3. **Considerations / Tradeoffs / Decisions** — what we considered, what we rejected, what is intentionally deferred.
4. **Todos** — concrete, file-level engineering tasks.

> **Three invariants the whole design respects:**
>
> 1. **Skill content AND inventory are live.** Admin uploads propagate to all active sandbox pods in seconds via the generic bundle pipeline (event-driven push — see `sandbox-file-sync.md`). Lifecycle triggers (session setup, snapshot restore, manual refresh) reconcile any push that didn't land. The agent learns about new skills on its next turn — OpenCode rescans `.agents/skills/` per turn and re-exposes the inventory via its native `skill` tool (§10). No AGENTS.md regeneration needed for skill changes.
> 2. **Bundle is content; DB row is metadata.** Slug, name, description, grants are admin-controlled in DB. The bundle is just the agent-facing instructions and supporting files.
> 3. **Universal layer is consumer-blind.** `backend/onyx/skills/` knows nothing about sessions, sandboxes, or `.agents/skills`. Consumers translate their state into the materializer's inputs and choose the destination path.

---

## Table of contents

1. [Scope and goals](#1-scope-and-goals)
2. [Architecture overview](#2-architecture-overview)
3. [Data model](#3-data-model)
4. [Built-in skill registry](#4-built-in-skill-registry)
5. [Custom skill bundle format & validation](#5-custom-skill-bundle-format--validation)
6. [Materializer](#6-materializer)
7. [Universal API surface](#7-universal-api-surface)
8. [Craft consumer integration](#8-craft-consumer-integration)
9. [Sandbox delivery (local + Kubernetes)](#9-sandbox-delivery-local--kubernetes)
10. [AGENTS.md generation](#10-agentsmd-generation)
11. [Per-session user experience](#11-per-session-user-experience)
12. [Snapshot fidelity](#12-snapshot-fidelity)
13. [Admin UI](#13-admin-ui)
14. [Multi-tenancy](#14-multi-tenancy)
15. [Migration & deploy ordering](#15-migration--deploy-ordering)
16. [Orphan cleanup](#16-orphan-cleanup)
17. [Testing](#17-testing)
18. [Out-of-scope / deferred](#18-out-of-scope--deferred)

---

## 1. Scope and goals

### Context
Craft sessions today symlink a single image-baked `/workspace/skills` directory into every session. Adding/changing a skill requires a Dockerfile change and a full image rebuild. There is no admin upload path, no access control, no way for customers to ship their own skills, no per-session rendered content (e.g. injecting a user's accessible sources into `company-search`), and no path for non-Craft consumers (future Persona/Chat) to reuse this system.

V1 introduces a first-class Skills primitive: an Onyx-wide layer that consumers (starting with Craft) materialize their skills from. Customers can upload skill bundles via an admin UI; built-in skills continue to live on disk but are now materialized at runtime, not baked into the sandbox image.

### Proposed Solution
Two paths through one primitive:
- **Built-in skills** — on-disk directories, registered in code at app boot. Always available, no admin toggle.
- **Custom skills** — admin-uploaded zip bundles in Postgres + FileStore, gated by per-user/per-group grants.

Each session, the materializer resolves the available built-ins + the user's accessible custom skills into `.agents/skills/`. A read-only panel in the session UI shows what's active; inline "Using `<skill>`" indicators appear when the agent reads a `SKILL.md`.

Universal primitive at `backend/onyx/skills/`. Craft consumer adapter at `backend/onyx/server/features/build/skills/`. Persona/Chat are not wired up in V1 — but the primitive is consumer-blind so they can adopt later without schema changes.

#### Three-tier authorship model

The product's long-term model has **three** authorship tiers. V1 ships only the first two:

| Tier | Status in V1 | Author | Default visibility | Sharing |
|---|---|---|---|---|
| **Built-in** | ✅ Ships in V1 | Onyx engineering (deploy artifact) | Org-wide if its requirements are satisfied | n/a |
| **Custom (admin-authored)** | ✅ Ships in V1 | Tenant admin | Admin chooses at upload (private / org-wide / specific groups) | Admin controls via grants |
| **User-authored** | ❌ Deferred to V1.5 | Any tenant user | Private to author | Author shares with specific groups/users; can request admin promotion → admin-authored |

The data model and API shape leave room for V1.5 without schema migration: the `source` discriminator extends to `"user"`, the deleted `Skill__User` join comes back, and `author_user_id` already captures authorship in V1. The full V1.5 deferral entry is in §19.

### Considerations / Tradeoffs / Decisions
- **V1 is infrastructure, not a brand surface.** Skills V1 ships as plumbing — the data model, primitive, sandbox-delivery pipeline, and an admin upload path. The product positioning (naming, marketing surface, marketplace narrative, discoverability moments) is intentionally **not** in scope for V1. A separate product workstream layers the brand surface on top of this infrastructure once V1 is stable. Implication for V1 decisions: when in doubt, prefer the choice that doesn't lock in marketing surface (internal-leaning copy, no in-product launch moments, no marketplace UI).
- **Universal-from-day-one vs Craft-now-refactor-later.** Chose universal. The cost is one extra module path; the savings are avoiding a future migration of customer-facing API routes when Persona/Chat adopts skills.
- **No admin toggle for built-ins in V1.** Customers can't disable a built-in for their org without unsetting the underlying dependency (e.g. `GEMINI_API_KEY`). Accepted because the alternative (per-org `org_enabled` state) doubles the admin surface and creates a registry-vs-DB drift class of bugs. Reversible later via a `builtin_skill_org_state` table.
- **No `is_available` capability checks in V1.** Deferred to the separate "interception layer" project, which will handle missing-secret cases at request time. Built-ins are unconditionally available. Registry API leaves room to add the hook back non-breakingly.
- **No per-session user pinning/opt-out.** Users get the full union of built-ins + accessible customs automatically. Natural-language override only. Adding control later is one column/join table — no risk of being painted into a corner.
- **AGENTS.md inlines everything; no threshold logic.** Expected V1 skill counts are well under any reasonable threshold. The discovery fallback would be an untested code path. Telemetry will catch context-bloat before users do.

### Todos
- [ ] Confirm rollout sequencing with infra (api_server + sandbox image must roll together; see §15).
- [ ] Open a tracking issue or epic linking all the work items below.

---

## 2. Architecture overview

### Context
Where does each piece live, what depends on what, and how does the universal/consumer split actually look in the file tree.

### Proposed Solution

```
┌─────────────────────────────────────────────────────────────────────┐
│ UNIVERSAL LAYER — backend/onyx/skills/                              │
│                                                                     │
│   registry.py     BuiltinSkillRegistry (process-wide singleton)     │
│   bundle.py       validate_custom_bundle, compute_bundle_sha256     │
│   materialize.py  materialize_skills(dest, user, db, render_ctx)    │
│   render.py       template placeholder rendering                    │
│   __init__.py     public surface re-exports                         │
│                                                                     │
│   DB:  backend/onyx/db/skill.py                                     │
│        Tables: skill, skill__user_group                             │
│                                                                     │
│   API: backend/onyx/server/features/skills/api.py                   │
│        /api/admin/skills   (admin CRUD + grants)                    │
│        /api/skills         (read-only user list)                    │
└────────────────────────────────▲────────────────────────────────────┘
                                 │
       ┌─────────────────────────┴───────────────────────────┐
       │ CRAFT CONSUMER — backend/onyx/server/features/build/skills/
       │                                                     │
       │   builtins_registration.py                          │
       │   materialize_adapter.py                            │
       │   api.py     /api/build/sessions/{id}/skills        │
       │             (panel data source: reads manifest)     │
       └─────────────────────────────────────────────────────┘
```

The universal layer exposes:
- `BuiltinSkillRegistry` (singleton, populated at boot).
- `validate_custom_bundle(zip_bytes) -> ManifestMetadata | InvalidBundleError`.
- `materialize_skills(dest_path, user, db, render_ctx) -> SkillsManifest`.
- DB ops (`list_skills_for_user`, `fetch_skill_for_user`, `create_skill`, `replace_skill_bundle`, `patch_skill`, `delete_skill`).
- HTTP routers mounted at `/api/admin/skills` and `/api/skills`.

The Craft consumer:
- Registers Craft's built-ins via the universal `BuiltinSkillRegistry`.
- Calls `materialize_skills(...)` from sandbox session setup.
- Exposes `/api/build/sessions/{id}/skills` for the frontend panel (reads the manifest from the running session — snapshot-accurate).

### Design decision: built-ins live in code, not the DB

> _Why two storage paths instead of one unified table._

A natural-looking simplification is to unify built-ins and custom skills under one storage model — seed built-in bundles into FileStore on install, store rows in the `skill` table alongside customs, drop the two-path API merge. We considered it and chose the split. The reason is **lifecycle, not aesthetics.**

**Built-ins are deploy artifacts.** They version with the codebase, get tested in CI alongside the code that uses them, and ship with the release. An engineer commits `pptx/SKILL.md`, 30 minutes later it's in prod for every tenant.

**Customs are user data.** They version per upload, persist across deploys, belong to the tenant. A customer drops a zip and 5 seconds later it's available to their org.

Unifying them forces one of those lifecycles to bend:

- If built-ins inherit the user-data lifecycle, every deploy needs a reconciliation step: compare the on-disk bundle's sha256 against the DB row, decide whether to clobber an admin's edits, tombstone removed built-ins, backfill new tenants, serialize `SkillRequirement.check` callables into rule expressions. None of these are unsolvable; all of them are real code, real tests, real ops complexity.
- If customs inherit the deploy-artifact lifecycle, they have to live in the repo — not viable, by definition.

The current split costs ~30 lines (a route-handler merge in `api.py`) plus ~10 lines (a second loop in `materialize_skills`). The unified path would cost an upgrade-detection seeder, multi-tenant backfill, reconciliation logic on every deploy, and per-tenant FileStore growth for redundant bundle copies. Lopsided.

**Revisit when:** a customer requests per-org enable/disable of built-ins. Even then, the cheaper move is a separate `builtin_skill_org_state` table (one row per tenant per built-in, ~50 lines) — the bundles still stay on disk. Listed in §19 deferred.

### Considerations / Tradeoffs / Decisions
- **Why a separate `backend/onyx/server/features/skills/api.py` rather than inlining endpoints into the build feature.** Customers will integrate against `/api/admin/skills`. Moving that path later (when Persona/Chat adopts) is a breaking change. Putting it at the universal layer on day one is cheap.
- **Why `BuiltinSkillRegistry` is a singleton, not DB-backed.** See the "built-ins live in code" decision above. One-liner: deploy lifecycle ≠ user-data lifecycle.
- **Why the panel data source is a Craft-specific endpoint, not the universal `/api/skills`.** The panel reflects what's *actually visible to the running session* via `.agents/skills/.skills_manifest.json` (which resolves through the symlink to `/skills/.skills_manifest.json` — the live pod-level state). Under live propagation (§12) this is usually identical to what `/api/skills` would return for the user, but the session-scoped path is the right shape for the build consumer and remains useful for debugging when sandbox state is the question.

### Todos
- [ ] Create empty module skeletons:
  - [ ] `backend/onyx/skills/__init__.py`
  - [ ] `backend/onyx/skills/registry.py`
  - [ ] `backend/onyx/skills/bundle.py`
  - [ ] `backend/onyx/skills/materialize.py`
  - [ ] `backend/onyx/skills/render.py`
  - [ ] `backend/onyx/db/skill.py`
  - [ ] `backend/onyx/server/features/skills/__init__.py`
  - [ ] `backend/onyx/server/features/skills/api.py`
  - [ ] `backend/onyx/server/features/build/skills/__init__.py`
  - [ ] `backend/onyx/server/features/build/skills/builtins_registration.py`
  - [ ] `backend/onyx/server/features/build/skills/materialize_adapter.py`
  - [ ] `backend/onyx/server/features/build/skills/api.py`

---

## 3. Data model

### Context
We need persistence for custom skills (admin-uploaded). Built-ins are code-resident and need no rows. The data model should mirror the Persona access-control pattern so reviewers immediately recognize the shape, and should require no application-level tenant-scoping (Onyx's schema-per-tenant model handles that).

### Proposed Solution

Three tables in the per-tenant (private) schema, plus two new `FileOrigin` enum values.

```python
# backend/onyx/db/models.py

class Skill(Base):
    """A custom (admin-uploaded) skill. One bundle per skill; re-upload replaces."""
    __tablename__ = "skill"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Admin-controlled metadata (editable post-creation via PATCH).
    slug:        Mapped[str] = mapped_column(String(64), nullable=False)
    name:        Mapped[str] = mapped_column(String,     nullable=False)
    description: Mapped[str] = mapped_column(Text,       nullable=False)

    # Bundle bytes (single, replaced on re-upload).
    bundle_file_id:    Mapped[str] = mapped_column(String,     nullable=False)
    bundle_sha256:     Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_metadata: Mapped[dict[str, Any]] = mapped_column(PGJSONB, nullable=False)

    author_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    is_public:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled:    Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # NULL = active; set to now() on soft-delete. Sweep ages blob cleanup off this.

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup", secondary="skill__user_group", viewonly=True,
    )

    __table_args__ = (
        # Partial unique index: slug uniqueness only among non-deleted rows.
        # Lets a slug be reused after the original is soft-deleted (matches the
        # §5 validator rule "slug not already used by another non-deleted custom").
        Index(
            "ux_skill_slug",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Skill__UserGroup(Base):
    __tablename__ = "skill__user_group"
    skill_id:      Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),
        ForeignKey("skill.id",     ondelete="CASCADE"), primary_key=True)
    user_group_id: Mapped[int]  = mapped_column(Integer,
        ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True)
```

```python
# backend/onyx/configs/constants.py:373

class FileOrigin(str, Enum):
    ...
    SANDBOX_SNAPSHOT = "sandbox_snapshot"
    SKILL_BUNDLE     = "skill_bundle"   # NEW
    USER_FILE        = "user_file"
```

Slug rules:
- Regex: `^[a-z][a-z0-9-]{0,63}$`.
- Per-tenant unique among **non-deleted** rows (via schema isolation + the partial unique index on `slug WHERE deleted_at IS NULL`). Slugs can be reused after a skill is soft-deleted; the application validator (§5) enforces the same rule so failures surface as `INVALID_REQUEST`, not raw DB constraint violations.
- Globally reserved against built-in slugs.
- **Mutable** post-creation via PATCH.

### Considerations / Tradeoffs / Decisions
- **No `builtin_skill_state` table.** Built-ins are code, not data. Adding a row per built-in per tenant would create drift between the registry and DB.
- **No `skill_version` table.** One bundle per skill; re-upload replaces. Customers needing rollback keep prior zips locally. Versioning is real work (UI, "promote" semantics, retention rules) we don't need to do yet.
- **`bundle_file_id` and `manifest_metadata` are `NOT NULL`.** A skill always has a bundle. The first upload is creation; subsequent are replacements. There is no "skill row with no bundle yet" intermediate state.
- **`name` and `description` are denormalized DB columns, not extracted on-demand from JSONB.** Lets list endpoints and search use indexable strings; saves a JSONB lookup on every read. The cost is a single source-of-truth: admin sets them; bundle frontmatter only pre-fills the upload form.
- **Slug mutability is safe under snapshot fidelity.** Existing sessions reference the old slug via their snapshot; new sessions get the new slug. No data migration on rename.

### Todos
- [ ] Add `Skill`, `Skill__UserGroup` to `backend/onyx/db/models.py`.
- [ ] Add `SKILL_BUNDLE` to `FileOrigin` in `backend/onyx/configs/constants.py:373`.
- [ ] Create Alembic migration `backend/alembic/versions/<hash>_skills.py`:
  - [ ] `CREATE TABLE skill` with all columns + indexes.
  - [ ] `CREATE TABLE skill__user_group` with FKs.
  - [ ] `ALTER TYPE fileorigin ADD VALUE 'skill_bundle'`.
- [ ] Verify with `alembic -n schema_private upgrade head` on a fresh EE tenant.
- [ ] Implement DB ops in `backend/onyx/db/skill.py`:
  - [ ] `list_skills_for_user(user, db) -> list[Skill]` — public OR group-grant, with **`enabled = True AND deleted_at IS NULL`** filter (mirror `fetch_persona_by_id_for_user` at `backend/onyx/db/persona.py:81`, minus the direct-user-grant branch). This is the materializer's source — disabled or soft-deleted skills never make it into `/skills/`.
  - [ ] `fetch_skill_for_user(skill_id, user, db) -> Skill | None` — same `enabled = True AND deleted_at IS NULL` filter as `list_skills_for_user`. A user can't reach a disabled/deleted skill via single-item fetch either.
  - [ ] `fetch_skill_for_admin(skill_id, db) -> Skill | None` — **`deleted_at IS NULL`** only (no `enabled` filter; admins need to fetch disabled skills to re-enable them). Engineer-only undelete bypasses this helper with a raw query.
  - [ ] `list_skills_for_admin(db) -> list[Skill]` — **`deleted_at IS NULL`** only (no `enabled` filter; the admin UI displays disabled skills so admins can re-enable them). Soft-deleted rows are hidden by default; engineer-only undelete bypasses this helper.
  - [ ] `create_skill(slug, name, description, bundle_file_id, bundle_sha256, manifest_metadata, is_public, author_user_id, db) -> Skill`.
  - [ ] `replace_skill_bundle(skill_id, new_bundle_file_id, new_sha256, new_manifest_metadata, db) -> Skill` (returns old_bundle_file_id so caller can delete the blob after commit).
  - [ ] `patch_skill(skill_id, slug=None, name=None, description=None, is_public=None, enabled=None, db) -> Skill` (partial update).
  - [ ] `replace_skill_grants(skill_id, group_ids, db) -> None` (atomic: delete + insert in one transaction).
  - [ ] `delete_skill(skill_id, db) -> None` — soft-delete by setting `deleted_at = func.now()`. Blob is NOT deleted inline; the sweep (§16) ages out the blob and hard-deletes the row after 14 days.

---

## 4. Built-in skill registry

### Context
Built-in skills are on-disk directories. We need a way for each feature that ships built-ins (today only the build feature) to register them with the universal layer at app boot. We also need this registration to be cheap to extend later (e.g. adding capability checks when the interception layer lands).

### Proposed Solution

A process-wide singleton populated at app boot. Each registration captures a `(slug, source_dir, name, description, requirements)` tuple — name/description are read from the source dir's `SKILL.md` frontmatter at registration time and cached. `requirements` declare the org-level dependencies the skill needs to run (e.g. a configured Gemini provider for `image-generation`).

```python
# backend/onyx/skills/registry.py

class SkillRequirement(BaseModel):
    """Org-level dependency a built-in skill needs to be usable.
    Frozen — registered at app boot, never mutated."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key: str                                 # stable id, e.g. "image_generation_provider"
    name: str                                # human label, e.g. "Image generation provider"
    description: str                         # what's missing + where to set it up
    configure_url: str                       # e.g. "/admin/configuration/image-generation"
    check: Callable[[Session], bool]         # cheap; returns True if satisfied
                                              # (arbitrary_types_allowed=True covers Callable + Session)

class BuiltinSkill(BaseModel):
    """In-memory entry in the BuiltinSkillRegistry. Populated at boot from
    on-disk source directories."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    slug: str
    source_dir: Path
    name: str                                # from SKILL.md frontmatter
    description: str                         # from SKILL.md frontmatter
    has_template: bool
    requirements: tuple[SkillRequirement, ...] = ()   # all must be satisfied

class BuiltinSkillRegistry:
    """Process-wide. Populated at boot; treated as immutable after."""

    def register(
        self,
        slug: str,
        source_dir: Path,
        requirements: Sequence[SkillRequirement] = (),
    ) -> None:
        """Reads SKILL.md(.template) frontmatter, validates slug, stores entry."""

    def list_all(self) -> list[BuiltinSkill]: ...
    def list_satisfied(self, db: Session) -> list[BuiltinSkill]:
        """Built-ins whose requirements all check True. Used by the materializer."""
    def evaluate_for_admin(self, db: Session) -> list[BuiltinSkillStatus]:
        """Per-built-in: each requirement + satisfied bool. Used by /api/admin/skills."""
    def get(self, slug: str) -> BuiltinSkill | None: ...
    def reserved_slugs(self) -> set[str]: ...
```

Registration happens at app boot. Each feature owns its own registration module and imports requirement checks from the modules that own the dependencies:

```python
# backend/onyx/server/features/build/skills/builtins_registration.py

from onyx.db.image_generation import get_default_image_generation_config
from onyx.skills.registry import SkillRequirement

_SKILLS_DIR = Path(__file__).parent.parent / "sandbox/kubernetes/docker/skills"

def register_craft_builtins(registry: BuiltinSkillRegistry) -> None:
    registry.register(slug="pptx", source_dir=_SKILLS_DIR / "pptx")

    registry.register(
        slug="image-generation",
        source_dir=_SKILLS_DIR / "image-generation",
        requirements=[
            SkillRequirement(
                key="image_generation_provider",
                name="Image generation provider",
                description="Configure an image-generation provider (e.g. Gemini, OpenAI) before this skill can run.",
                configure_url="/admin/configuration/image-generation",
                check=lambda db: get_default_image_generation_config(db) is not None,
            ),
        ],
    )

    # bio-builder, company-search registered when their on-disk dirs land.
```

`backend/onyx/main.py` calls `register_craft_builtins(BuiltinSkillRegistry.instance())` after DB init, before serving requests.

### Considerations / Tradeoffs / Decisions
- **Why register at boot rather than on-demand.** Boot-time catches slug collisions and missing source dirs at process start, not mid-request.
- **Why frontmatter parsing at registration, not materialization.** Lets the admin UI show built-in name/description without reading from disk on every request.
- **Slug collision = fail loud at boot.** Deploy-time bug; operator must fix.
- **`requirements` is structured, not a bare callable.** Letting the admin UI render *what's missing* and *where to fix it* requires more than a bool. A `SkillRequirement` carries enough metadata for the badge, the drawer detail, and the deep-link CTA. A future `is_disabled_by_admin(db)` flavor can be added the same way without changing call sites.
- **Pydantic, not `@dataclass`.** Both `SkillRequirement` and `BuiltinSkill` use `BaseModel` with `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)` to match the codebase convention (Pydantic models dominate ~96% of backend type definitions). `arbitrary_types_allowed` is required because `Callable` and `Session` aren't Pydantic-native. Frozen gives immutability + hashability for set membership without needing `__hash__` boilerplate.
- **Checks must be cheap and side-effect-free.** They run on every session-start materialization and every `GET /api/admin/skills`. Confirmed: all V1 checks are single-row DB lookups (`get_default_image_generation_config(db)`, `fetch_existing_llm_providers(db, ...)`) — sub-millisecond.
- **Checks come from the feature module that owns the dependency.** `get_default_image_generation_config` lives in `backend/onyx/db/image_generation.py`; the registration module just composes them. Keeps coupling sane and tests independent.
- **OR composition for "either of these works".** If a skill needs *one of N* providers, the requirement's `check` is `lambda db: provider_a(db) or provider_b(db)`. Single requirement, composed boolean — keeps the admin UI clean (one "Needs setup" entry, not N).
- **No shared/bundled requirements between skills in V1.** If two skills need the same dep, each declares it independently. The admin will see two near-identical "Needs setup" CTAs but they both deep-link to the same configure page — acceptable noise for V1. If we ship five+ skills sharing one dep, factor out a `SHARED_REQUIREMENTS` module then.
- **Users never see unavailable built-ins.** Materializer skips them entirely → not in `.agents/skills/`, not in `AGENTS.md`. The agent doesn't know they could exist. No ghosted-but-disabled UI for users.

### Todos
- [ ] Implement `SkillRequirement` dataclass in `backend/onyx/skills/registry.py`.
- [ ] Implement `BuiltinSkillRegistry`:
  - [ ] Singleton accessor (`BuiltinSkillRegistry.instance()`).
  - [ ] `register(slug, source_dir, requirements=[])` — read frontmatter, validate slug, raise on duplicate or missing SKILL.md.
  - [ ] `list_all()`, `list_satisfied(db)`, `evaluate_for_admin(db)`, `get(slug)`, `reserved_slugs()`.
- [ ] Implement `register_craft_builtins(registry)` in `backend/onyx/server/features/build/skills/builtins_registration.py`:
  - [ ] `pptx` — no requirements.
  - [ ] `image-generation` — requires `get_default_image_generation_config(db) is not None`, deep-link to `/admin/configuration/image-generation`.
- [ ] Wire the call into `backend/onyx/main.py` startup.
- [ ] Startup integration tests:
  - [ ] `assert registry.get("pptx") is not None` after app boot.
  - [ ] `registry.list_satisfied(db)` excludes `image-generation` when no provider is configured; includes it after one is added.

---

## 5. Custom skill bundle format & validation

### Context
Admins upload skill bundles as zip files. We need a validator that runs synchronously in the upload request, rejects malformed/dangerous bundles before anything persists, and extracts metadata for storage.

### Proposed Solution

Bundle format:

```
<bundle.zip>
├── SKILL.md           (required — agent instructions, frontmatter optional)
├── scripts/           (optional)
└── *.md               (optional supporting docs)
```

Validation is a single synchronous pass in the upload request. Bundles cap at 100 MiB uncompressed — sub-second on commodity hardware. Failure short-circuits before anything persists.

**Validation rule table:**

| Rule | Failure | `OnyxError` code |
|---|---|---|
| Zip parses | `bundle is not a valid zip` | `INVALID_REQUEST` |
| `SKILL.md` at root | `SKILL.md missing at bundle root` | `INVALID_REQUEST` |
| No `*.template` files | `custom skills cannot ship templates` | `INVALID_REQUEST` |
| No path traversal (`..`, absolute, normalize stays in root) | `bundle entry escapes root` | `INVALID_REQUEST` |
| No symlinks (zip entry external attrs flag) | `bundle contains a symlink` | `INVALID_REQUEST` |
| Per-file uncompressed ≤ 25 MiB | `file 'X' exceeds 25 MiB` | `INVALID_REQUEST` |
| Total uncompressed ≤ 100 MiB (streaming check) | `bundle exceeds 100 MiB uncompressed` | `INVALID_REQUEST` |
| Slug regex `^[a-z][a-z0-9-]{0,63}$` | `invalid slug` | `INVALID_REQUEST` |
| Slug not in registry reserved set | `slug 'X' is reserved` | `INVALID_REQUEST` |
| Slug not already used by another non-deleted custom | `slug 'X' already exists` | `INVALID_REQUEST` |

Bundle frontmatter (in `SKILL.md`) is **optional** in V1. If present and parseable, `name` / `description` are captured into `manifest_metadata` and pre-filled into the upload form. They are not authoritative — admin-typed values win.

`manifest_metadata` JSONB shape:

```json
{
  "frontmatter": {"name": "deal-summary", "description": "..."},
  "files": [
    {"path": "SKILL.md",       "size": 1832},
    {"path": "scripts/run.sh", "size": 412}
  ],
  "total_uncompressed_bytes": 2244,
  "validator_version": 1
}
```


### Considerations / Tradeoffs / Decisions
- **Synchronous validation, not async.** The bundle is ≤ 100 MiB; full validation is sub-second. Async would buy us nothing and create a "skill exists but isn't usable yet" intermediate state.
- **Streaming uncompressed-size check.** Zip declares decompressed sizes, but a malicious zip can lie. We track the actual decompressed byte count as we read entries and abort on cap.
- **Frontmatter not required.** Earlier draft required `frontmatter.name == slug`. Dropped because admin types slug/name/description in the upload form — bundle frontmatter is a pre-fill convenience, not a contract.
- **Template files explicitly rejected.** Reserved for built-ins because `SkillRenderContext` shape is still evolving. Don't want customer bundles referencing fields we're still designing.
- **`validator_version` in manifest_metadata.** Future rule changes can identify which version validated a persisted bundle. Useful for forward-compat without forcing re-validation.

### Todos
- [ ] Implement `validate_custom_bundle(zip_bytes: bytes, slug: str) -> ManifestMetadata` in `backend/onyx/skills/bundle.py`:
  - [ ] Parse zip with `zipfile.ZipFile`.
  - [ ] Streaming iterator that decompresses entries, tracking running total. Abort on cap.
  - [ ] Per-entry: check path normalization, symlink flag (`external_attr` bit), per-file size.
  - [ ] Reject any `*.template` file.
  - [ ] Verify `SKILL.md` exists at root.
  - [ ] Parse `SKILL.md` frontmatter (YAML); capture optionally.
  - [ ] Build and return `ManifestMetadata` dict.
- [ ] Implement `compute_bundle_sha256(zip_bytes: bytes) -> str` — deterministic (raw bytes, not zip-content-hash; we want to detect "this is the exact same upload" not "this has the same contents in a different zip order").
- [ ] Implement `_safe_unzip(zip_bytes: bytes, dest: Path) -> None` — used by the materializer; re-checks traversal + symlinks defensively (defense in depth).
- [ ] Define `InvalidBundleError(OnyxError)` subclass with code `INVALID_REQUEST` for clean propagation.
- [ ] Unit tests: each validation rule rejected; known-good fixture accepted; sha256 deterministic across timestamp differences.

---

## 6. Materializer

### Context
Given a user and a destination path, write every skill the user has access to into `dest/<slug>/`, along with a `.skills_manifest.json` index. This is the consumer-blind core of the system. Craft calls it from sandbox setup; future consumers call it the same way.

### Proposed Solution

```python
# backend/onyx/skills/materialize.py

class SkillRenderContext(BaseModel):
    user_name:   str | None = None
    user_email:  str | None = None
    backend_url: str | None = None
    session_id:  UUID | None = None
    extra:       dict[str, str] = Field(default_factory=dict)

class SkillManifestEntry(BaseModel):
    slug: str
    name: str
    description: str
    source: Literal["builtin", "custom"]

class SkillsManifest(BaseModel):
    builtin: list[SkillManifestEntry]
    custom:  list[SkillManifestEntry]

def materialize_skills(
    dest_path: Path,
    user: User,
    db_session: Session,
    render_context: SkillRenderContext,
) -> SkillsManifest:
    """Resolve and write every accessible skill into dest_path/<slug>/.
    Writes dest_path/.skills_manifest.json. Returns the manifest."""
```

Algorithm:

1. Ensure `dest_path` exists and is empty.
2. `builtins = BuiltinSkillRegistry.instance().list_satisfied(db_session)` — only built-ins whose requirements all check True. Unsatisfied built-ins are skipped silently; admins see them as "Needs setup" in the admin UI.
3. `customs = list_skills_for_user(user, db_session)` — single SQL query, public-OR-group-grant, filtered to `enabled = True AND deleted_at IS NULL`. Disabled or soft-deleted skills never reach the materialized set.
4. For each built-in:
   - `shutil.copytree(source_dir, dest_path/slug)`.
   - If `SKILL.md.template` exists in the copied directory:
     - `rendered = render_template_placeholders(template_text, render_context)`.
     - Write `rendered` to `SKILL.md`.
     - Delete the `.template` file.
   - Capture `SkillManifestEntry(slug, name, description, source="builtin")`.
5. For each custom:
   - `blob_bytes = file_store.read_file(custom.bundle_file_id, mode="b")`.
   - `_safe_unzip(blob_bytes, dest_path/slug)`.
   - Capture `SkillManifestEntry(slug=custom.slug, name=custom.name, description=custom.description, source="custom")`.
6. Build `SkillsManifest`; write `dest_path/.skills_manifest.json`.
7. Return the manifest.

**Template rendering** lives in `backend/onyx/skills/render.py`. Mustache-style placeholders (`{{user_name}}`, `{{accessible_sources}}`). Unknown placeholders left as literal `{{foo}}` with a `logger.warning(slug, placeholder)`.

### Considerations / Tradeoffs / Decisions
- **No process-level cache.** Removing today's `_skills_cache` in `agent_instructions.py`. Skills are now per-session (per-user templating, per-user grants). Caching would mean per-user keying, more cost than benefit.
- **`shutil.copytree` for built-ins.** Simpler than reading bytes individually. The source dirs are small (a few small files).
- **Defensive re-unzip for customs.** Validator catches traversal/symlinks at upload, but a customer might exploit a validator bug. Re-checking on each materialization is cheap and avoids a single-point-of-failure.
- **Manifest source discriminator (`builtin` / `custom`).** Used by the admin UI and frontend panel for badging. AGENTS.md doesn't use it (it lists all skills uniformly).

### Todos
- [ ] Implement `SkillRenderContext`, `SkillManifestEntry`, `SkillsManifest` Pydantic models in `backend/onyx/skills/materialize.py`.
- [ ] Implement `materialize_skills(...)` per the algorithm above.
- [ ] Extract placeholder logic from `backend/onyx/server/features/build/sandbox/util/agent_instructions.py` into `backend/onyx/skills/render.py` as `render_template_placeholders(text: str, ctx: SkillRenderContext) -> str`.
- [ ] Public re-exports in `backend/onyx/skills/__init__.py`:
  - [ ] `materialize_skills`, `SkillRenderContext`, `SkillsManifest`, `SkillManifestEntry`, `BuiltinSkillRegistry`, `validate_custom_bundle`.
- [ ] External-dependency unit test: materialize for a fixture user with 1 granted custom + 1 not-granted custom + 2 built-ins → assert directory layout + manifest contents.

---

## 7. Universal API surface

### Context
Admins need CRUD on custom skills + a unified listing including built-ins. Users need a read-only view of what they have access to (for admin tooling preview + future user-facing UI). All endpoints raise `OnyxError`; no `response_model=` (typed function signatures only — per `CLAUDE.md`).

### Proposed Solution

**Admin endpoints** (`/api/admin/skills` — admin-only dependency):

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| `GET` | `/api/admin/skills` | — | List all skills: `{builtin: [...], custom: [...]}` |
| `POST` | `/api/admin/skills/custom` | multipart: bundle, slug, name, description, is_public, group_ids? | Create custom skill atomically (bundle + metadata + grants) |
| `PATCH` | `/api/admin/skills/custom/{id}` | JSON: `{slug?, name?, description?, is_public?, enabled?}` | Partial update; doesn't touch bundle or grants |
| `PUT` | `/api/admin/skills/custom/{id}/bundle` | multipart: bundle | Replace bundle bytes |
| `PUT` | `/api/admin/skills/custom/{id}/grants` | JSON: `{group_ids}` | Atomic grant replacement |
| `DELETE` | `/api/admin/skills/custom/{id}` | — | Soft-delete (sets `deleted_at = now()`) |

**User endpoints** (`/api/skills` — authenticated user):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/skills` | Skills accessible to current user (forward-looking, for fresh sessions) |

**Internal endpoints** (sandbox-to-api_server, pod-token auth):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/internal/sandbox/{sandbox_id}/bundles/skills/tarball` | Stream tarball of materialized skills for the sandbox's user. Implemented as the generic bundle tarball endpoint (see `sandbox-file-sync.md`); skills is the first consumer. Runs `SkillsBundle.materialize(...)` via `materialize_skills(...)` from §6 and streams `application/x-tar`. Honors `If-Modified-Since`. See §9. |
| `POST` | `/api/sandbox/{sandbox_id}/refresh` | User-triggered "refresh sandbox" — server kubectl-execs `refresh-bundle skills` (and any other registered bundles) for the target pod. Defined by the bundle abstraction (see `sandbox-file-sync.md`). |

**Response models** (FastAPI returns these directly via typed function signatures):

```python
class SkillsAdminList(BaseModel):
    builtin: list[BuiltinSkillAdmin]
    custom:  list[CustomSkillAdmin]

class BuiltinSkillAdmin(BaseModel):
    slug: str
    name: str
    description: str
    has_template: bool
    available: bool                              # True iff every requirement satisfied
    requirements: list[RequirementStatus]        # empty if skill has no requirements

class RequirementStatus(BaseModel):
    key: str
    name: str
    description: str
    configure_url: str
    satisfied: bool

class CustomSkillAdmin(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    is_public: bool
    enabled: bool
    bundle_sha256: str
    bundle_size_bytes: int
    granted_group_ids: list[int]
    author_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

class SkillsForUser(BaseModel):
    builtin: list[SkillSummary]
    custom:  list[SkillSummary]

class SkillSummary(BaseModel):
    slug: str
    name: str
    description: str
    source: Literal["builtin", "custom"]
    skill_id: UUID | None   # set for customs, None for built-ins
```

**Create-custom-skill flow** (`POST /api/admin/skills/custom`):
1. Parse multipart fields.
2. Validate slug regex; check against reserved set; check uniqueness in DB.
3. Read bundle bytes (capped at 100 MiB).
4. `validate_custom_bundle(bundle_bytes, slug)` → `ManifestMetadata` or raise.
5. `compute_bundle_sha256(bundle_bytes)`.
6. `file_store.save_file(bundle_bytes, origin=SKILL_BUNDLE, ...)` → `bundle_file_id`.
7. `create_skill(...)` inserts row.
8. `replace_skill_grants(skill_id, group_ids, db)` (no-op if `is_public=True` or list is empty).
9. Return `CustomSkillAdmin`.

If any step fails after files are saved to the FileStore, the route handler must delete those orphaned blobs before re-raising. (The orphan sweep in §16 is a safety net, not the primary cleanup path.)

**Replace-bundle flow** (`PUT /api/admin/skills/custom/{id}/bundle`):
1. Fetch existing `skill`. Capture `old_bundle_file_id`.
2. Read + validate new bundle (same as create).
3. Save new bundle blob.
4. `replace_skill_bundle(...)` updates row.
5. **After DB commit succeeds**: delete `old_bundle_file_id` from FileStore.

If DB commit fails, new blobs are orphaned (caught by sweep). If FileStore delete fails after commit, old blobs are orphaned (caught by sweep). Either way the system reaches a consistent state.

### Considerations / Tradeoffs / Decisions
- **Single POST for create + grants.** Atomic. No "skill exists with no grants" intermediate state for a UI to misrender.
- **PATCH supports slug change.** Snapshot fidelity means this is safe. New sessions get the new slug; existing sessions keep theirs.
- **No paging on `/api/admin/skills`.** Expected count is well under 100 per tenant. Add paging if/when this changes.
- **`SkillSummary` returns `skill_id` for customs only.** Built-ins are identified by slug; customs by UUID (the slug can change). This lets the frontend route correctly.
- **`enabled` flag exists on the DB row but is not in the V1 admin UI.** Reserved for future "temporarily disable without deleting" use case. The schema is forward-compatible; admin UI can add a toggle later without migration.

### Todos
- [ ] Implement universal admin router in `backend/onyx/server/features/skills/api.py`:
  - [ ] `GET /api/admin/skills` — combine `registry.list_all()` + `list_skills_for_admin(db)`.
  - [ ] `POST /api/admin/skills/custom` — full create flow per above.
  - [ ] `PATCH /api/admin/skills/custom/{id}` — call `patch_skill(...)`. Re-validate slug uniqueness if changing.
  - [ ] `PUT /api/admin/skills/custom/{id}/bundle` — full replace flow.
  - [ ] `PUT /api/admin/skills/custom/{id}/grants` — call `replace_skill_grants(...)`.
  - [ ] `DELETE /api/admin/skills/custom/{id}` — call `delete_skill(...)`. Sets `deleted_at = now()`; sweep (§16) ages out the blob + row after 14 days.
- [ ] Implement user router (same file):
  - [ ] `GET /api/skills` — built-ins + customs visible to user.
- [ ] Define Pydantic response models in the same file.
- [ ] Wire router into `backend/onyx/main.py` via `app.include_router(...)`.
- [ ] Add the admin dependency to admin routes (matches existing admin-gating pattern; see `backend/onyx/server/features/persona/...`).
- [ ] External-dependency unit tests for each endpoint covering happy path + each validation failure.

---

## 8. Craft consumer integration

### Context
Craft sessions today symlink a single image-baked skills dir. We need to replace that with: register built-ins at boot, call `materialize_skills(...)` at session start, and serve the panel data source endpoint.

### Proposed Solution

**Three pieces:**

#### 8.1 `builtins_registration.py`
Already covered in §4. Registers Craft's built-ins via the universal registry.

#### 8.2 `materialize_adapter.py`
Called from sandbox session setup. Builds a `SkillRenderContext` from session state, calls the materializer, returns the staging dir for the sandbox manager to deliver.

```python
# backend/onyx/server/features/build/skills/materialize_adapter.py

def materialize_for_session(
    session: BuildSession,
    user: User,
    db: Session,
) -> tuple[Path, SkillsManifest]:
    """Materialize this user's skills into a temp staging dir.
    Returns (staging_dir, manifest). Caller is responsible for delivery + cleanup."""
    staging_dir = Path(tempfile.mkdtemp(prefix="skills-stage-"))
    render_ctx = SkillRenderContext(
        user_name=user.name,
        user_email=user.email,
        backend_url=settings.BACKEND_URL,
        session_id=session.id,
        extra={
            "accessible_sources": render_accessible_cc_pairs(user, db),
        },
    )
    manifest = materialize_skills(staging_dir, user, db, render_ctx)
    return staging_dir, manifest
```

`render_accessible_cc_pairs(user, db)` produces the rendered list referenced by the `company-search` built-in's `SKILL.md.template` (see `search.md` for the source-listing format).

#### 8.3 Panel data source endpoint

```python
# backend/onyx/server/features/build/skills/api.py

@router.get("/api/build/sessions/{session_id}/skills", response_model=None)
def get_session_skills(session_id: UUID, ...) -> SkillsManifest:
    """Read .skills_manifest.json from the running session.
    Snapshot-accurate — reflects what was materialized at session start,
    not the user's current grants."""
    session = fetch_build_session(session_id, user, db)
    if session is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")
    manifest_text = sandbox_manager.read_file_from_session(
        session, ".agents/skills/.skills_manifest.json"
    )
    return SkillsManifest.model_validate_json(manifest_text)
```

`sandbox_manager.read_file_from_session(...)` is a new helper on `SandboxManagerBase` (both Kubernetes and local backends implement it). For Kubernetes, it's `kubectl exec ... cat <path>`; for local, it's a direct file read from the mounted workspace.

### Considerations / Tradeoffs / Decisions
- **Why a temp staging dir, not direct-write into the sandbox.** Decoupling materialization from delivery means the universal layer doesn't need to know how to write into a Kubernetes pod vs a local workspace. The build consumer handles delivery.
- **Why include `accessible_sources` in `render_context.extra` rather than as a well-known field.** It's Craft-specific (driven by Onyx connector/CC-pair state). A future Persona consumer wouldn't need it. Well-known fields are for keys multiple consumers need.
- **Panel endpoint reads manifest from the live session, not the DB.** Snapshot fidelity (§12) means current grants can differ from what's actually in the session. Reading the manifest is the only correct source.
- **Cleanup of `staging_dir`.** Sandbox manager deletes it after delivery succeeds. If delivery fails, the manager logs and deletes anyway — the staging dir is ephemeral.

### Todos
- [ ] Implement `materialize_for_session(...)` in `backend/onyx/server/features/build/skills/materialize_adapter.py`.
- [ ] Implement or reuse `render_accessible_cc_pairs(user, db)` — confirm with `search.md` whether this helper already exists; if not, implement it (likely calling `get_connector_credential_pairs_for_user`).
- [ ] Add `read_file_from_session(session, path) -> str` to `SandboxManagerBase` and implement in both `KubernetesSandboxManager` and the local manager.
- [ ] Implement `GET /api/build/sessions/{id}/skills` in `backend/onyx/server/features/build/skills/api.py`.
- [ ] Wire the new router into the build feature's router registration.
- [ ] Update `backend/onyx/server/features/build/sandbox/manager/directory_manager.py:325`:
  - [ ] Remove the `setup_skills(sandbox_path)` method (`shutil.copytree` from `self._skills_path`).
  - [ ] Drop the `skills_path` constructor argument and `_skills_path` attribute.
  - [ ] Update callers in `directory_manager.py:78`, `:309`.
- [ ] Replace the `ln -sf /workspace/skills` block in `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:1338-1340` (see §9 for delivery details).

---

## 9. Sandbox delivery — pod-level `/skills/` refreshed via the generic bundle pipeline

### Context
Skills are not per-session user data — they're shared infrastructure that should reflect the **current admin state**, not whatever was current when a session started. Earlier drafts put skill content into each session's workspace (and therefore into snapshots), which froze skills at session start and made admin uploads fail to reach existing sessions. The right model: **skills live at a pod-level path mounted into the sandbox, refreshed on-demand from api_server, and symlinked into each session.**

(One pod = one sandbox = one user. Sessions are conversations within a sandbox. `sandbox_id ≠ session_id` — confirmed against `kubernetes_sandbox_manager.py:367`.)

The delivery mechanism (tarball endpoint, in-pod refresh script, Celery push pipeline, lifecycle triggers, write-through cache) is **not skills-specific**. It's the generic **Sandbox File Sync bundle abstraction** described in [`sandbox-file-sync.md`](./sandbox-file-sync.md). Skills is the first consumer of that pipeline; user_library and future org-wide admin files follow the same shape. This section captures only the skills-specific surface area.

### Proposed Solution

#### 9.1 Layout

```
┌─────────────────────── pod (sandbox, one user) ──────────────────────┐
│                                                                       │
│   /skills/                  ← pod-level mount, refreshed via bundle   │
│      pptx/                                                            │
│         SKILL.md                                                      │
│         scripts/...                                                   │
│      image-generation/                                                │
│      company-search/                                                  │
│      deal-summary/                                                    │
│      .skills_manifest.json                                            │
│                                                                       │
│   /workspace/sessions/                                                │
│      <session-A>/                                                     │
│         .agents/skills  →  /skills/    (symlink)                      │
│         AGENTS.md       ← regen at session start + on snapshot restore│
│         (user files, attachments, outputs, ...)                       │
│      <session-B>/                                                     │
│         .agents/skills  →  /skills/    (symlink)                      │
│         AGENTS.md                                                     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

Snapshots only carry user files + AGENTS.md + the bare symlink. **Skill content is never in a snapshot.** On resume, the symlink is reconstructed; skills come from current admin state — which means the pod's entrypoint runs `refresh-bundle skills` before the agent starts (covered by the bundle pipeline's session-setup / session-wakeup triggers).

#### 9.2 SkillsBundle — the skills-specific bundle implementation

The generic bundle pipeline delegates "what to put in the tarball" to a bundle class. For skills, that's `SkillsBundle` (in `backend/onyx/sandbox_sync/bundles/skills.py`), implementing the `SandboxBundle` interface from `sandbox-file-sync.md`:

```python
class SkillsBundle(SandboxBundle):
    bundle_key = "skills"
    mount_path = "/skills/"
    cache_on_mutation = True    # tenant fan-out → write-through cache helps

    def materialize(self, db, ctx):
        """Yield BundleEntry for every file the agent should see under /skills/.

        Walks built-in skills on disk (the source tree in the Onyx repo) and
        custom skills (zip blobs in OnyxFileStore, one per skill). For each
        custom skill, reads its zip via file_store.read_file(bundle_file_id),
        streams members directly into the output tar — no on-disk unpack.
        Applies per-user template rendering (see §6 — materialize_skills)
        for built-ins that declare a template.
        """
        ...

    def pod_label_selector(self, tenant_id, user_id):
        # Tenant-wide push: all pods in the tenant see the same skills
        # (filtered per-pod by user grants at materialize time via ctx.user_id).
        return f"onyx.app/tenant-id={tenant_id}"

    def last_modified(self, db, ctx):
        return db.query(func.max(Skill.updated_at)).filter(
            Skill.tenant_id == ctx.tenant_id
        ).scalar()
```

The tarball endpoint (`GET /api/internal/sandbox/{sandbox_id}/bundles/skills/tarball`), in-pod refresh script (`/usr/local/bin/refresh-bundle skills`), Celery push tasks (`propagate_bundle_change` + `refresh_pod_bundle`), pod entrypoint refresh, manual refresh button, and write-through tarball cache **all live in the bundle pipeline** — see `sandbox-file-sync.md`. The skills implementation contributes only the `SkillsBundle` class plus the call to `enqueue_change(db, tenant_id, "skills")` at every skill admin mutation.

#### 9.3 Refresh triggers (recap)

Per the bundle pipeline, `/skills/` is refreshed in four situations — no background polling:

| Trigger | How |
|---|---|
| Skill admin mutation | `enqueue_change` populates the write-through cache, then Celery fan-out kubectl-execs `refresh-bundle skills` on every tenant pod |
| Pod boot (session setup) | Pod entrypoint runs `refresh-bundle skills` before exec'ing the agent |
| Snapshot restore (session wakeup) | Same entrypoint code path — a restored pod is freshly booted from its own perspective |
| User clicks "refresh sandbox" | `POST /api/sandbox/{sid}/refresh` kubectl-execs `refresh-bundle skills` on the target pod |

End-to-end propagation on the happy path: ~1–3 seconds from skill mutation to all tenant pods. The lifecycle triggers recover the ~5% push-failure tail (kubectl-exec into not-Ready pods, etc.).

#### 9.4 Per-session setup — just a symlink

Both backends collapse to:

```python
def _setup_session_skills_symlink(self, session_path: Path) -> None:
    """Point .agents/skills at the pod-level /skills/ mount."""
    target = session_path / ".agents" / "skills"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink() if target.is_symlink() else shutil.rmtree(target)
    target.symlink_to("/skills", target_is_directory=True)
```

Called from `setup_session_workspace` **and** from `_regenerate_session_config` (the snapshot-restore helper at `kubernetes_sandbox_manager.py:1736`). Each is one line added.

No more tarball-into-pod for session setup. No more `materialize_for_session` invoked on the api_server during session creation — `materialize_skills` runs only when the refresh endpoint is called.

#### 9.5 Dockerfile changes (skills-specific)

The shared `refresh-bundle` script and entrypoint hooks are owned by the bundle pipeline (see `sandbox-file-sync.md` files manifest). The skills-specific Dockerfile changes are:

```dockerfile
# REMOVE (legacy):
COPY skills/ /workspace/skills/
RUN mkdir -p /workspace/skills

# ADD:
RUN mkdir -p /skills    # mount path; refresh-bundle populates it
```

The on-disk source at `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/` **stays** — still read at runtime by the api_server side of `SkillsBundle.materialize` (built-in skill source-of-truth).

#### 9.6 Pod auth, scope, and path contract

- **Auth.** The pod uses the existing sandbox bearer token (same one the bundle pipeline already requires; see `sandbox-file-sync.md`). No skills-specific token.
- **Scope decision: tenant-wide push.** `SkillsBundle.pod_label_selector` returns `onyx.app/tenant-id={tenant_id}` — every active pod in the tenant gets the refresh. Pods whose user doesn't have access to a particular skill just receive a tarball where that skill is absent (filtered per-sandbox by `ctx.user_id` at materialize time). Simpler than computing the "affected users" set on the api_server side, and avoids races where access changes between the access query and the push.
- **Path contract.** `.agents/skills/` (not `.opencode/skills/`) — OpenCode's discovery walks `.agents/skills/`, `.opencode/skills/`, and `.claude/skills/` (per [OpenCode docs](https://opencode.ai/docs/skills/)). `.agents/` is the agent-runtime-agnostic choice and stays the cross-runtime contract.

#### 9.7 Hooking skill mutations into the bundle pipeline

Every skill admin mutation calls `enqueue_change(db, tenant_id, "skills")` after the DB commit. With `SkillsBundle.cache_on_mutation = True`, `enqueue_change` synchronously materializes the new tarball into Redis (the write-through cache from `sandbox-file-sync.md`) and then enqueues the propagate task. By the time any tenant pod curls the tarball endpoint, the cache key already exists — 1 materialization for the entire fan-out.

Five touch points in `backend/onyx/server/features/skills/api.py`:

```python
# After successful commit on:
#   POST   /api/admin/skills/custom
#   PATCH  /api/admin/skills/custom/{id}
#   PUT    /api/admin/skills/custom/{id}/bundle
#   PUT    /api/admin/skills/custom/{id}/grants
#   DELETE /api/admin/skills/custom/{id}

from onyx.sandbox_sync.enqueue import enqueue_change
enqueue_change(db, tenant_id, "skills")
```

Pod labels: sandbox provisioning sets `onyx.app/tenant-id` (per `kubernetes_sandbox_manager.py:619`, beside the existing `onyx.app/sandbox-id`). Single-line addition. Same label is shared with future bundles.

### Considerations / Tradeoffs / Decisions

- **Why pod-level `/skills/` instead of per-session materialization.** Lets admin uploads/grants/deletes propagate to all sessions (new and existing). Sessions don't carry skill content into snapshots → snapshots stay small. Per-user template rendering still works because one pod = one user.
- **Why the bundle abstraction owns delivery.** Skills is one of several systems that need "files materialized on api_server, delivered to running sandbox pods" — user_library has the same shape, future org-wide admin files will too. Building a skills-only pipeline (the earlier draft of this section did) duplicated infrastructure each consumer would inevitably need. The bundle abstraction in `sandbox-file-sync.md` is that infrastructure; skills is the first consumer.
- **Why `cache_on_mutation = True`.** Skills fan out tenant-wide. Without a write-through cache, N tenant pods curling the tarball endpoint simultaneously after an admin mutation would each trigger an independent materialize. Write-through populates the cache once at the mutation site (before the propagate task is enqueued), so the fan-out becomes 1 materialize + N cache reads. See `sandbox-file-sync.md` §"Write-through tarball cache."
- **Materializer runs on api_server, not in the pod.** The pod only needs to extract a tarball — no FileStore access, no DB queries, no bundle validation. The sandbox image stays minimal. Bundle blobs never traverse a fan-out path.
- **Atomic rename pattern.** Handled by the generic `refresh-bundle` script — readers see strictly old or strictly new, never partial.
- **AGENTS.md regen on resume happens but no longer matters for skills.** `_regenerate_session_config` at `kubernetes_sandbox_manager.py:1736-1809` regenerates AGENTS.md on snapshot restore. We add one line to also (re)create the `.agents/skills` symlink. AGENTS.md itself no longer carries skill information (§10) — OpenCode's per-turn `skill` tool rescan handles inventory. The symlink is the only skill-related restore step.
- **Pod boot is the bootstrap.** Pod entrypoint runs `refresh-bundle skills` before exec'ing the agent (per `sandbox-file-sync.md`). No separate initContainer needed; the same code path serves both fresh provisioning and snapshot restore.
- **Local backend.** Dev-mode skips the kubectl-exec path; the local sandbox manager invokes `refresh-bundle skills` as a subprocess (same script, no kubectl needed). Or even simpler: dev-mode reads `/skills/` directly from the api_server's host FS via a bind mount.
- **Self-healing when api_server is briefly unavailable.** A failed `refresh-bundle` call exits non-zero; the next lifecycle trigger (manual refresh button, next session setup) reconciles. The pod keeps serving its current `/skills/` in the meantime.
- **Manual refresh button (changed from earlier drafts).** Earlier drafts argued no manual button was needed because polling caught everything. With polling removed in favor of lifecycle triggers (per `sandbox-file-sync.md`), the user-facing "Refresh sandbox" button **is** that lifecycle trigger for an active session. Wired in the Craft sandbox menu next to other sandbox-control actions.

### Todos

**Generic bundle pipeline** (owned by `sandbox-file-sync.md` — included here for sequencing visibility; implement these first, skills depends on them):
- [ ] Stand up `backend/onyx/sandbox_sync/` (bundle ABC, registry, enqueue, tarball builder, cache) per `sandbox-file-sync.md` files manifest.
- [ ] Stand up `backend/onyx/background/celery/tasks/sandbox_sync/` (propagate, refresh tasks).
- [ ] Add `GET /api/internal/sandbox/{sid}/bundles/{key}/tarball` endpoint.
- [ ] Add `POST /api/sandbox/{sid}/refresh` endpoint.
- [ ] Add `refresh-bundle` in-pod script + entrypoint hook that iterates registered bundles before exec'ing the agent.
- [ ] Add `onyx.app/tenant-id=<id>` label to sandbox pods at provisioning (`kubernetes_sandbox_manager.py:619`, beside the existing `onyx.app/sandbox-id` label).
- [ ] Frontend "Refresh sandbox" button wired to `POST /api/sandbox/{sid}/refresh`.

**Skills consumer of the bundle pipeline:**
- [ ] Implement `SkillsBundle` in `backend/onyx/sandbox_sync/bundles/skills.py`: `cache_on_mutation = True`, `materialize` walks built-ins on disk + reads custom skill zip blobs from FileStore (streaming members directly into the tar), `pod_label_selector` returns `onyx.app/tenant-id={tenant_id}`, `last_modified` returns `MAX(skill.updated_at) WHERE tenant_id=...`.
- [ ] Register `SkillsBundle` in `backend/onyx/sandbox_sync/bundles/__init__.py`.
- [ ] Reuse `materialize_skills(...)` from §6 inside `SkillsBundle.materialize` — same rendering / template logic, just plumbed through the bundle interface instead of writing to a temp dir.
- [ ] Hook `enqueue_change(db, tenant_id, "skills")` at the 5 mutation endpoints after their respective commits: POST custom, PATCH custom, PUT bundle, PUT grants, DELETE custom.
- [ ] Edit Dockerfile: drop `COPY skills/`, drop `mkdir -p /workspace/skills`, add `mkdir -p /skills` (the mount path the bundle pipeline writes to).
- [ ] Implement `_setup_session_skills_symlink(session_path)` (one helper for both K8s and local backends).
- [ ] Call `_setup_session_skills_symlink(...)` from `setup_session_workspace` (replaces the old skill-materialization step).
- [ ] Call `_setup_session_skills_symlink(...)` from `_regenerate_session_config` at `kubernetes_sandbox_manager.py:1736` so resumed sessions also get the symlink. AGENTS.md regen is already there.
- [ ] Verify snapshot tarball **excludes** `/skills/` (it's a separate mount; should be naturally excluded, but confirm).
- [ ] Remove `directory_manager.setup_skills(...)` and its callers (we no longer materialize per-session).
- [ ] Local backend: invoke `refresh-bundle skills` as a subprocess (or bind-mount the host `/skills/` directly for dev). Same code path; no kubectl needed.
- [ ] Add a feature flag `SKILLS_MATERIALIZATION_V2_ENABLED` for staged rollout (see §15).

**Tests:**
- [ ] Integration test (skills-specific): admin upload → assert pod's `/skills/` reflects new content within ~5 sec. The bundle pipeline's own tests (push path, lifecycle triggers, 304, write-through cache) live in `backend/tests/integration/tests/sandbox_sync/`.
- [ ] Failure test: simulate kubectl-exec failure → assert manual refresh or next lifecycle trigger reconciles.
- [ ] Update existing integration tests for sandbox setup that referenced the old skills path.

---

## 10. AGENTS.md skill section — dropped; OpenCode handles discovery natively

### Context
Earlier drafts inlined a skill list into AGENTS.md via a `{{AVAILABLE_SKILLS_SECTION}}` placeholder filled by `build_skills_section(skills_path)`. Empirical testing (2026-05) on a live session confirmed this is **redundant**: OpenCode has a native `skill` tool that exposes the skill inventory to the agent via the tool description, and **OpenCode rebuilds that tool description from the filesystem on every turn**. Adding a new SKILL.md under `.agents/skills/<slug>/` mid-conversation makes the skill visible to the agent on the next turn with zero AGENTS.md regeneration.

> Per [OpenCode docs](https://opencode.ai/docs/skills/): "Skills are loaded on-demand via the native `skill` tool — agents see available skills and can load the full content when needed." The tool description includes the structured `<available_skills>` inventory.
>
> Test (2026-05-12): with a Craft session running, dropped `.opencode/skills/zarf-the-magnificent/SKILL.md` directly into the session FS. Asked the agent to list its skills on the next turn. Agent returned `zarf-the-magnificent` with the test description. **Confirmed: OpenCode rescans per-turn.**

### Proposed Solution

**Delete the skill-list section from AGENTS.md entirely.** No `{{AVAILABLE_SKILLS_SECTION}}` placeholder, no `build_skills_section(...)` helper, no `.skills_manifest.json` consumption inside AGENTS.md. The agent learns about skills from OpenCode's native `skill` tool, which auto-discovers from `.agents/skills/` on every turn.

AGENTS.md retains only the content OpenCode doesn't generate for us:
- User context (name, email, role)
- Org info section
- LLM / NextJS config
- Environment / methodology / system-prompt boilerplate

### Considerations / Tradeoffs / Decisions

- **OpenCode is the source of truth for skill inventory.** The agent's awareness of "what skills exist" comes from OpenCode's tool description, not from text we inline in AGENTS.md. Inlining would just duplicate (and risk diverging from) what OpenCode already provides.
- **Live inventory propagation is free.** Because OpenCode rescans per turn, the moment `/skills/<slug>/` appears (via our refresh loop in §9), the next agent turn sees it. No regen step needed on our side.
- **Snapshot resume is also free.** OpenCode rescans on start AND on each turn. Resumed sessions inherit the current state of `/skills/` without anything in `_regenerate_session_config` touching skill content.
- **`.skills_manifest.json` is now a frontend-only artifact.** Written by the materializer in §6 for the panel data source (§11); the agent never reads it.
- **What if we switch off OpenCode** (custom harness, Codex, etc.)? The harness would need its own equivalent of OpenCode's `skill` tool — either inlining into the system prompt (what we were going to do) or building its own auto-discovery. Either way, the on-disk layout at `.agents/skills/<slug>/SKILL.md` stays — that's the cross-runtime contract per the `.agents/` choice from earlier.

### Todos
- [ ] **Remove** the `{{AVAILABLE_SKILLS_SECTION}}` placeholder from `AGENTS.template.md`.
- [ ] **Remove** the `available_skills_section = build_skills_section(skills_path)` line and the `content.replace("{{AVAILABLE_SKILLS_SECTION}}", ...)` line at `agent_instructions.py:481-495`.
- [ ] **Delete** `build_skills_section(skills_path)` at `agent_instructions.py:267-296`.
- [ ] **Delete** `_scan_skills_directory(...)` if unused after the above (likely).
- [ ] **Delete** `_skills_cache` and `_skills_cache_lock` (also unused after the above).
- [ ] Verify no other call sites reference `build_skills_section` or `{{AVAILABLE_SKILLS_SECTION}}`.
- [ ] Smoke test: launch a session, confirm the agent lists current skills correctly without the inlined section.

---

## 11. Per-session user experience

### Context
The user needs to know what skills are available in their session, and ideally see when the agent uses one. The current model is: nothing — skills are invisible plumbing. We're adding a panel + inline mentions.

### Proposed Solution

#### 11.1 Skills panel
A read-only sidebar/section in the Craft session UI. Lists active skills with name, description, and source badge (Platform/Custom). Clicking a skill opens a drawer/modal with the SKILL.md content for that skill.

Data source: `GET /api/build/sessions/{id}/skills` (returns the manifest). Frontend renders the list with letter-monogram avatars derived from the slug — no per-skill icon assets in V1.

For the SKILL.md preview drawer, frontend can either:
- Add a new backend endpoint `GET /api/build/sessions/{id}/skills/<slug>/content` returning the rendered SKILL.md text.
- Or trust the manifest (no SKILL.md preview in V1, defer to V2).

**V1 decision:** add the content endpoint. It's small, and "what does this skill actually do?" is the obvious next user question after seeing the panel.

#### 11.2 Inline mentions
When the agent reads `.agents/skills/<slug>/SKILL.md`, the chat surfaces "Using `<slug>`" inline. OpenCode already streams tool-use / file-read events through the Onyx backend to the frontend. The frontend pattern-matches: if a read event's path matches `.agents/skills/<slug>/SKILL.md`, render the indicator.

No backend changes needed for inline detection. The path contract `.agents/skills/<slug>/SKILL.md` is the dependency.

#### 11.3 No user control
No toggles. To suppress a skill in the current turn, the user tells the agent in the prompt.

### Considerations / Tradeoffs / Decisions
- **Why read from session manifest, not `/api/skills`.** Snapshot fidelity (§12) — current grants can diverge from the session's frozen state. The user should see what their session actually has.
- **Why no per-session opt-out.** Adds data model state and UI complexity without proven need. Future addition is a single table + column.
- **Inline detection lives in the frontend.** The agent stream is already a frontend concern; making this another consumer of the existing event flow keeps coupling minimal.
- **Path contract is load-bearing.** If we ever materialize to a path other than `.agents/skills/<slug>/SKILL.md`, the frontend matcher breaks. Treat this as part of the system's external contract.

### Todos
- [ ] Implement frontend skills panel component:
  - [ ] `web/src/app/craft/.../SkillsPanel.tsx` — fetches via `SWR_KEYS.buildSessionSkills(sessionId)` (defined in §13 todos), renders the list.
  - [ ] Skill row sub-component: letter-monogram avatar, name, description, source badge.
  - [ ] Click opens drawer showing SKILL.md preview.
- [ ] Implement `GET /api/build/sessions/{id}/skills/<slug>/content` returning the rendered SKILL.md as plain text.
- [ ] Mount the panel in the Craft session UI shell.
- [ ] Implement inline mention rendering:
  - [ ] In the chat-stream consumer, pattern-match tool-use/file-read events on the path regex `^\.agents/skills/([a-z][a-z0-9-]{0,63})/SKILL\.md$`.
  - [ ] Render "Using `<slug>`" inline at the matching position in the stream.
- [ ] Frontend tests for the panel (list renders, click opens drawer).
- [ ] Manual smoke: agent reads a SKILL.md in a test session → inline indicator appears.

---

## 12. Skill propagation — fully live (content + inventory)

### Context
Earlier drafts split propagation into two cadences: live `/skills/` content (~1-3 sec typical via push + ≤5 min safety net via polling) and per-conversation AGENTS.md inventory (regenerated only at session boundaries). Empirical testing of OpenCode's skill discovery (see §10) showed the second tier is unnecessary: **OpenCode rebuilds its native `skill` tool description from `.agents/skills/` on every turn**, so any change in `/skills/` propagates to the agent's inventory awareness on the next turn — without any AGENTS.md regen step.

### Proposed Solution

**One mechanism: the generic bundle pipeline (`sandbox-file-sync.md`), with skills as its first consumer.** Everything is live in seconds on the happy path; lifecycle triggers (session setup, snapshot restore, manual refresh) reconcile the failure tail without polling.

| Layer | Live? | How |
|---|---|---|
| **`/skills/` content** (SKILL.md + scripts + supporting files) | ✅ ~1-3 sec typical via push | Event-driven push from api_server on every admin mutation — `enqueue_change(db, tenant_id, "skills")` triggers write-through cache + tenant fan-out via the generic bundle pipeline (`sandbox-file-sync.md`). |
| **Push-failure recovery** | ✅ on next lifecycle event | Pod entrypoint runs `refresh-bundle skills` on session setup and snapshot restore; user can also click "Refresh sandbox" in the Craft UI. No background polling. |
| **Agent inventory awareness** | ✅ next turn after content refresh | OpenCode's native `skill` tool rescans `.agents/skills/` per turn and re-exposes the inventory in the tool description |
| **Session snapshot** | n/a | Doesn't include `/skills/` content — skills are pod-level infra, not session data |

End-to-end behavior: admin uploads a new skill → `enqueue_change` materializes the tarball once and writes it to Redis, then fans out kubectl-exec refresh-bundle to every active pod in the tenant (~1-3 sec, all hitting the cache) → next turn in any active session sees the new skill in OpenCode's `skill` tool description → agent can invoke immediately.

### Behavioral implications

| Admin event | Mid-conversation user | Next turn in same session | New session / resume |
|---|---|---|---|
| Upload new skill `X` | Doesn't see `X` yet | `X` appears in `skill` tool inventory; agent can invoke | Same — agent sees `X` from the start |
| Replace `X`'s bundle | Already-read SKILL.md content stays in agent's context for current actions | Next read of `.agents/skills/X/SKILL.md` gets new content | Same |
| Delete / revoke grant for `X` | `X` still in agent's prior turn context | `X` absent from next turn's inventory; reads to `/skills/X/` fail (dir gone after refresh) | `X` absent from inventory |
| Rename `X`'s slug | Old slug still in prior turn context | Old slug missing on next inventory; new slug present; agent's in-context reference to old slug fails on next file op | New slug present from start |
| Capability flip (e.g. `image-generation` provider removed) | Skill disappears from `/skills/` on next refresh | Skill absent from agent's next-turn inventory | Skill absent |

The Admin UI mutation copy is the same as in earlier drafts:

> "This change takes effect within a few seconds. Conversations currently in progress will see the new state on their next turn."

For deletes:
> "Files this skill wrote to user workspaces remain there until the sessions end."
*(Workspace persistence still applies to outputs the skill produced — `pptx`-generated decks, etc. Only the skill's own code stops being available.)*

### Considerations / Tradeoffs / Decisions

- **Why no boundary-stable inventory anymore.** The earlier "AGENTS.md regenerated only at session boundaries" model was designed to prevent the agent's *list of available skills* from shifting mid-conversation. Investigation showed this was based on a wrong assumption — OpenCode doesn't use AGENTS.md for skill awareness in the first place. The agent's inventory comes from OpenCode's `skill` tool, which is per-turn already. So we're not adding mid-conversation drift; we're just acknowledging it was already happening at the OpenCode layer.
- **Typical propagation: 1-3 sec via push.** Lifecycle triggers (session setup, snapshot restore, manual "Refresh sandbox" button) recover the ~5% push-failure tail. No background polling.
- **No skill-immutability invariant.** Earlier drafts had "Sessions are skill-immutable after start" — fully reversed.
- **Snapshot size impact.** Snapshots no longer carry skill content. Customs at 10+ MiB × 20 per tenant × every snapshot — storage cost is gone.
- **Mid-conversation user-visible behavior.** A user's agent might confidently invoke `deal-summary` in turn 5 using SKILL.md content read earlier; admin deletes it; turn 6 the skill is gone from inventory. Agent gets a missing-dir error on next attempt and reports it. This is essentially the same behavior we'd have had at the boundary model — admins were never going to delete skills "carefully" relative to in-flight conversations.
- **Workspace persistence (separate concern).** Files a skill *generated and wrote into the session workspace* persist across snapshot/resume. The skill *itself* doesn't. Admin delete modal calls both out.
- **No "kill switch."** A revoked skill stops being readable on next refresh + next agent turn. Running agents that already loaded SKILL.md content might still act on it in flight (within the current turn). Sub-5-minute kill needs a different mechanism (deferred).
- **Cross-harness implication.** If we ever swap OpenCode for a different agent runtime (custom harness, Codex, etc.), the new runtime needs its own per-turn skill rescanning equivalent — either via its own `skill` tool, by reading the directory each turn, or by including the inventory in the system prompt and regenerating it per turn. The on-disk `.agents/skills/<slug>/` contract stays; only the consumption pattern changes.

### Todos
- [ ] **Remove** the earlier invariant `"Sessions are skill-immutable after start"` from the top of the doc.
- [ ] **Add** an invariant docstring in `backend/onyx/skills/__init__.py`: `"Skill content and inventory are both live (~1-3 sec typical via event-driven push through the bundle pipeline; lifecycle triggers — session setup, snapshot restore, manual refresh — reconcile the failure tail; OpenCode rescans per turn)."`
- [ ] Update admin UI mutation modals (§13) to the new copy: "takes effect within a few seconds."
- [ ] Confirm snapshot tar (`SnapshotManager` / s5cmd flow) does NOT include `/skills/` — it's a separate mount, should be naturally excluded, but verify in `backend/onyx/server/features/build/sandbox/manager/snapshot_manager.py`.
- [ ] Confirm `_regenerate_session_config` at `kubernetes_sandbox_manager.py:1736` (re)creates the `.agents/skills` symlink on resume. (AGENTS.md regen there is no longer needed for skill purposes — see §10.)
- [ ] Integration test `test_live_skill_propagation.py`: start session, upload a new custom, wait for push to propagate (≤5 sec in test), verify the new skill is readable inside `/skills/` AND the agent's `skill` tool lists it on the next turn.
- [ ] Integration test `test_snapshot_excludes_skills.py`: pause a session, inspect the snapshot tar, confirm `/skills/` is absent. Resume and confirm `.agents/skills` is a symlink to `/skills/`, populated from current admin state.

---

## 13. Admin UI

### Context
Admins need a place to upload, edit, and manage custom skills, plus see what built-ins exist. The current Onyx admin pattern (see Persona admin) is the model to follow.

### Proposed Solution

Single page at `/admin/skills`. **One unified list** of built-ins + customs together, with badges differentiating source.

#### 13.1 List view
Columns: letter-monogram avatar, name (and slug as subtext), description (truncated), source badge (`Platform` / `Custom`), grants summary (customs only — "Org-wide" / "3 groups" / "5 users" / "Private"), updated_at, actions.

- **Built-in rows**: no action menu. Click row → drawer with read-only details (frontmatter, files list, on-disk path, requirements + status).
- **Custom rows**: action menu → Edit, Replace bundle, Manage grants, Enable/Disable, Delete.
- **Built-in availability**: Access column shows `Available` (green dot) when all requirements are satisfied, or `Needs setup · N missing` (warning) with an inline `Configure →` button that deep-links to the first unsatisfied requirement's `configure_url` (e.g. `/admin/configuration/image-generation`).
- **Search**: name + slug.
- **Filter**: source (All / Platform / Custom), enabled state, availability (All / Available / Needs setup).
- **Sort**: default by name; can sort by updated_at.
- **Empty state for customs.** When the admin has zero custom skills, the list area shows an inline "Get started" card with a `Download example skill (.zip)` button alongside the `Upload skill` CTA. The example zip is a minimal `hello-world` skill (SKILL.md + a short script) that the admin can download, inspect, edit, and re-upload as their first custom skill — removes the cold-start friction of "what does a skill zip even look like?". The zip ships in the deploy (`backend/onyx/server/features/skills/example_skill.zip` or similar) and is served by a static endpoint (`GET /api/admin/skills/example-bundle`).

##### Built-in requirements panel (in the read-only drawer)

When an admin opens a built-in's detail drawer, after the Description / Source / Files / Frontmatter sections, a **Requirements** section lists each declared requirement:

| Requirement | Status | Action |
|---|---|---|
| `Image generation provider` — *Configure an image-generation provider before this skill can run* | ✓ Satisfied   or   ✕ Not configured | `Configure →` (only when missing) |

If a built-in declares no requirements, the section is omitted.

#### 13.2 Upload modal
Triggered by "Upload skill" button at the top.

| Field | Required | Notes |
|---|---|---|
| Bundle (zip) | yes | Drag-and-drop or file picker. On selection, frontend reads frontmatter (client-side or via a `POST /preview-bundle` helper) to pre-fill name/description below. |
| Slug | yes | Regex-validated client-side. Pre-filled from frontmatter `name` if present. |
| Name | yes | Pre-filled from frontmatter if present. Editable. |
| Description | yes | Pre-filled from frontmatter if present. Editable. |
| Visibility | yes | Radio: Private / Org-wide / Specific groups. No default. |
| Groups picker | conditional | Multi-select group picker, only shown if "Specific" selected. (Individual-user grants are not in V1 — admins can create a single-member group if they need to share with one teammate.) |

**Pre-upload SKILL.md preview.** Once the admin selects a zip, the modal grows a **right-side preview pane** showing the parsed contents of `SKILL.md` (markdown-rendered) alongside a file list of everything else in the bundle. The admin sees the agent-facing instructions before they commit — this is the same content the LLM will read inside user sessions. Two reasons this matters:

1. **Social-attack mitigation.** A SKILL.md is essentially injected system-prompt content. Surfacing it forces the admin to read what they're authorizing rather than treating the upload as opaque code. The submit button is enabled but accompanied by an inline note ("This text is read by the agent inside user sessions; confirm it reflects your intent.") — soft attestation, not a hard checkbox, to avoid alert-fatigue dismissal.
2. **First-upload sanity check.** Catches "I uploaded the wrong zip" or "my SKILL.md has placeholder text" before it lands in production sessions.

Implementation: zip parsed client-side via `jszip` to extract `SKILL.md` + file list. No new endpoint needed — same client-side reading already used for frontmatter pre-fill.

Submit → `POST /api/admin/skills/custom` (multipart). Success: modal closes, skill appears in list. Validation failure: inline error under offending field with reason from `OnyxError`.

#### 13.3 Edit / Replace bundle / Grants
On a custom skill row:
- **Edit** (slug, name, description, visibility) → inline form or modal → `PATCH /api/admin/skills/custom/{id}` then `PUT .../grants` if visibility changed.
- **Replace bundle** → drag-and-drop new zip in a modal with confirmation copy → `PUT /api/admin/skills/custom/{id}/bundle`.
- **Manage grants** → reuses the visibility picker → `PUT /api/admin/skills/custom/{id}/grants`.

All mutation modals include the "takes effect within a few seconds" callout (see §12).

#### 13.4 Delete
Soft-delete confirmation modal:
> "Delete `<name>`? This removes the skill and revokes access for all granted users and groups. Conversations currently in progress will see the deletion on their next turn (typically within seconds). Files this skill *wrote into* user workspaces (generated outputs, attachments) remain there until the sessions end; the skill's own code stops being readable on the next refresh. This action can be reversed by an engineer in the database."

Submit → `DELETE /api/admin/skills/custom/{id}`. Row disappears from list. Hard delete is not a V1 admin action.

#### 13.5 Component reuse
Visibility picker (radio + group + user multi-select) is reused across upload modal, edit modal, and standalone grants editor. Build it once as a shared component.

### Considerations / Tradeoffs / Decisions
- **Unified list vs two sections.** Considered separating built-ins and customs into two sections. Chose unified with badges — ChatGPT-Apps-style — for cohesion. The absence of an action menu signals "this isn't user-controllable" without needing a second section.
- **Frontmatter pre-fill is convenience, not authority.** Admin can edit pre-filled values before submitting. After submit, the DB row is the source of truth.
- **No "default visibility" — admin chooses at upload time.** Silent defaults create accidental over- or under-sharing. Forcing a choice adds one click per upload (low friction).
- **Skill audit history is V1.5, not V1.** "Who uploaded what when" is partially satisfied by `created_at`/`updated_at`/`author_user_id` on the skill row. A proper audit log — every mutation (slug rename, grant change, bundle replace, delete) as an immutable event row, visible in an admin "Activity" tab — is the right shape for compliance-grade enterprises but adds a table, a write path on every mutation, and an admin UI surface. Deferred to V1.5; called out explicitly in §19. V1 customers who need richer history can derive it from app logs in the interim.
- **No bulk operations.** "Grant skill X to N groups at once" is the picker. "Delete N skills" isn't a workflow we've heard demand for.

### Todos

- [ ] **Register all new endpoints in `web/src/lib/swr-keys.ts` BEFORE implementing the components.** Per the repo convention (doc string at the top of `swr-keys.ts`): all `useSWR()` and `mutate()` calls must reference `SWR_KEYS` constants, never inline strings. ~170 existing references; **zero** inline `useSWR("...")` calls in the codebase. Add:
  ```ts
  // ── Skills ───────────────────────────────────────────────────────────────
  skills: "/api/skills",                                          // user-facing list
  adminSkills: "/api/admin/skills",                               // admin list (builtin + custom)
  adminSkillsCustom: "/api/admin/skills/custom",                  // POST (create)
  adminSkillsCustomById: (id: string) =>                          // PATCH, DELETE
      `/api/admin/skills/custom/${id}`,
  adminSkillsCustomBundle: (id: string) =>                        // PUT (replace bundle)
      `/api/admin/skills/custom/${id}/bundle`,
  adminSkillsCustomGrants: (id: string) =>                        // PUT (replace grants)
      `/api/admin/skills/custom/${id}/grants`,
  buildSessionSkills: (sessionId: string) =>                      // panel data source
      `/api/build/sessions/${sessionId}/skills`,
  buildSessionSkillContent: (sessionId: string, slug: string) =>  // SKILL.md preview
      `/api/build/sessions/${sessionId}/skills/${slug}/content`,
  ```
  Used by every list view, modal, and panel below. Mutation handlers (POST/PATCH/PUT/DELETE) call `mutate(SWR_KEYS.adminSkills)` after success to refresh the list.
- [ ] Create `web/src/app/admin/skills/page.tsx` — list view shell.
- [ ] List components:
  - [ ] `web/src/app/admin/skills/SkillsList.tsx` — table renderer.
  - [ ] `web/src/app/admin/skills/SkillRow.tsx` — single row with conditional action menu.
  - [ ] `web/src/app/admin/skills/SourceBadge.tsx` — Platform/Custom badge.
  - [ ] `web/src/app/admin/skills/BuiltinDetailDrawer.tsx` — read-only drawer for built-in rows.
- [ ] Upload modal:
  - [ ] `web/src/app/admin/skills/UploadSkillModal.tsx` — file picker, fields, visibility picker.
  - [ ] Client-side frontmatter pre-fill from selected zip (use a zip-reading lib like `jszip`).
  - [ ] **Pre-upload SKILL.md preview pane.** Right-side panel in the modal showing parsed-and-rendered `SKILL.md` + file list of the rest of the bundle. Reuses the same `jszip` reader as the frontmatter pre-fill. Includes inline soft-attestation note: "This text is read by the agent inside user sessions; confirm it reflects your intent."
- [ ] Example skill download:
  - [ ] Ship `backend/onyx/server/features/skills/example_bundle/` containing a minimal `hello-world` skill (SKILL.md + one short script). Built into the deploy artifact.
  - [ ] `GET /api/admin/skills/example-bundle` — static endpoint returning the bundle as `application/zip`. Auth: admin.
  - [ ] Empty-state card in `SkillsList.tsx`: when there are zero custom skills, render an inline "Get started" card with a `Download example skill (.zip)` link/button alongside `Upload skill`.
- [ ] Edit / replace / grants:
  - [ ] `web/src/app/admin/skills/EditSkillModal.tsx`.
  - [ ] `web/src/app/admin/skills/ReplaceBundleModal.tsx` with "takes effect within a few seconds" copy (per §12).
  - [ ] `web/src/app/admin/skills/VisibilityPicker.tsx` — shared component.
- [ ] Delete confirmation modal with the standard copy.
- [ ] Hook the page into the admin nav.
- [ ] Loading/error/empty states ("No skills yet — upload your first").
- [ ] Frontend type definitions matching backend Pydantic models (re-generate from OpenAPI if Onyx has that pipeline, else hand-write).

---

## 14. Multi-tenancy

### Context
Onyx EE is multi-tenant via schema-per-tenant (`alembic -n schema_private`). The Skills system must respect this without adding application-level tenant scoping.

### Proposed Solution
- **Skill tables live in the per-tenant (private) schema** — same as Persona. No `tenant_id` column needed; schema isolation handles it.
- **Slug uniqueness is per-tenant** by virtue of the schema-scoped unique index.
- **FileStore is already tenant-aware**: `save_file` calls `get_current_tenant_id()` and prefixes S3 keys with the tenant ID (`file_store.py:250-256`). `SKILL_BUNDLE` blobs inherit isolation automatically.
- **Built-ins are global** (code-resident, shared across tenants). Their slugs are reserved globally — every tenant's customs are blocked from using them.

### Considerations / Tradeoffs / Decisions
- **No `tenant_id` column.** Matches Onyx's existing schema-per-tenant pattern. Adding one would be a no-op (the schema already isolates) and would confuse readers.
- **Built-in slug reservation is global.** A tenant whose deployment doesn't actually have an `image-generation` capability still can't upload a custom skill named `image-generation`. Acceptable for V1 — the alternative (per-tenant reserved set) requires knowing per-tenant capability state, which we don't have until the interception layer lands.
- **No cross-tenant skill sharing.** A skill uploaded by tenant A is invisible to tenant B. V1 doesn't have a marketplace or share mechanism.

### Todos
- [ ] Confirm migration runs cleanly with `alembic -n schema_private upgrade head` on a fresh EE tenant.
- [ ] Add an integration test that creates skills in two tenants and verifies slug isolation: tenant A can have `deal-summary`, tenant B can independently have `deal-summary`, neither sees the other's.
- [ ] Document in the module docstring that no `tenant_id` is required because of schema isolation.

---

## 15. Migration & deploy ordering

### Context
The skills system changes both the api_server (new endpoints, new materializer, modified sandbox setup) and the sandbox image (drops `/workspace/skills`). A naïve deploy where the sandbox image rolls before the api_server learns to materialize would leave sessions with no skills. We need a feature-flag-gated rollout.

### Proposed Solution

**Feature flag**: `SKILLS_MATERIALIZATION_V2_ENABLED` (env var or settings entry).

**Rollout sequence:**
1. Deploy api_server with all new code, flag **off**. New endpoints exist but the sandbox setup path still uses the legacy `ln -sf /workspace/skills` block.
2. Deploy the new sandbox image (no `/workspace/skills`). Existing sessions started before this point keep working because the api_server still uses the legacy path, which falls back to "no skills" when the directory is missing.
3. **Flip the flag.** New sessions use the materialization path. Existing sessions are unaffected (snapshot fidelity).
4. Wait one release cycle for confidence.
5. Remove the flag and the legacy `ln -sf` code.

**Migration**: single Alembic revision creating `skill`, `skill__user_group`, and the two new `FileOrigin` enum values. Run with `alembic -n schema_private upgrade head` for EE.

### Considerations / Tradeoffs / Decisions
- **Why feature-flag rather than coordinated deploy.** Coordinated deploys are fragile (rolling restarts cross boundaries). The flag lets us roll images at our convenience and flip atomically.
- **Why preserve the legacy code path during step 2.** If a session starts in the window between sandbox image rollout and flag flip, it should still work — the legacy path's "no skills available" fallback is acceptable for a brief window.
- **No data migration.** Existing Craft sessions just pick up the new flow at their next start (after flag flip).

### Todos
- [ ] Add `SKILLS_MATERIALIZATION_V2_ENABLED` to `backend/onyx/configs/...` (settings or env-var pattern; match existing flag conventions).
- [ ] Guard the materialization-adapter call in sandbox setup with the flag. If off, fall back to a no-op (which results in "no skills available" — fine for the brief window).
- [ ] Create the Alembic migration.
- [ ] Document the rollout sequence in the PR description.
- [ ] After one release with the flag on, file a cleanup ticket: remove the flag, remove the legacy `ln -sf` code, remove the fallback path.

---

## 16. Orphan cleanup

### Context
FileStore blobs are saved before the DB row is committed. If a request crashes between save and commit, the blobs are orphaned. Both replace-bundle and delete-skill paths also need to delete old blobs. We need a defensive sweep to catch the rare crash case.

### Proposed Solution
Weekly Celery beat task. Two retention paths converge in one sweep:

1. **Orphan blobs** — FileStore records with `origin=SKILL_BUNDLE` that no `skill` row references (crash between blob save and DB commit). Age off the FileStore record's own `created_at`.
2. **Aged soft-deletes** — Skill rows with `deleted_at < now() - 14 days`. Delete the row's referenced blob, then hard-delete the row.

```python
# backend/onyx/background/celery/tasks/skills/tasks.py

RETENTION = timedelta(days=14)

@shared_task(name="cleanup_orphaned_skill_blobs")
def cleanup_orphaned_skill_blobs() -> None:
    """Two retention paths:
    1. Orphan blobs (no skill row references them) — crash recovery.
    2. Aged soft-deletes (skill.deleted_at older than retention) —
       finalize cleanup of admin-deleted skills.
    """
    with get_session_with_current_tenant() as db:
        # Path 1: orphans
        for file_id in _orphan_skill_blob_ids(db, older_than=RETENTION):
            file_store.delete_file(file_id)

        # Path 2: aged soft-deletes
        for skill in _aged_soft_deleted_skills(db, older_than=RETENTION):
            file_store.delete_file(skill.bundle_file_id)
            db.delete(skill)            # hard-delete the row after blob is gone
        db.commit()

# beat schedule:
"cleanup-orphaned-skill-blobs": {
    "task":     "cleanup_orphaned_skill_blobs",
    "schedule": timedelta(days=7),
    "options":  {"expires": 3600},   # required per CLAUDE.md
},
```

Inline cleanup (the primary path) happens in:
- `POST /api/admin/skills/custom`: if any step after a blob is saved fails, delete the blob before re-raising.
- `PUT /api/admin/skills/custom/{id}/bundle`: after DB commit succeeds, delete the old blob(s).
- `DELETE /api/admin/skills/custom/{id}`: sets `deleted_at = now()`. Blob stays on FileStore until aged out by the sweep (≥14 days later).

### Considerations / Tradeoffs / Decisions
- **`deleted_at` timestamp, not a bare `deleted` bool.** Earlier draft used a boolean — that can't carry retention age, so the sweep had no way to tell a recently-deleted skill from one deleted a year ago. `deleted_at IS NULL` = active; non-null = soft-deleted at that time. Strictly more information; same query ergonomics (`WHERE deleted_at IS NULL`).
- **Two retention paths, one sweep.** Conceptually different (crash recovery vs lifecycle cleanup) but the implementation merges naturally — both age out blobs older than 14 days, just keyed off different timestamps. Simpler than two separate tasks.
- **Hard-delete the row after the soft-delete retention window.** Otherwise soft-deleted rows accumulate indefinitely. After 14 days no one is going to undelete; row is gone, blob is gone.
- **Soft-delete + sweep vs hard-delete + immediate blob cleanup.** Soft-delete preserves a 14-day undelete window (engineer-only restore via DB). Slightly forgiving for accidental deletions.
- **Why weekly.** Orphans are rare. Aged soft-deletes accumulate, but a week of stale rows is acceptable; the sweep is idempotent.
- **`expires=3600` is required** per the `CLAUDE.md` Celery rule.
- **Task name in `name=` rather than auto-derived.** Stable name across refactors so beat scheduling doesn't break.

### Todos
- [ ] Implement `cleanup_orphaned_skill_blobs` in `backend/onyx/background/celery/tasks/skills/tasks.py`.
- [ ] Implement `_orphan_skill_blob_ids(db, older_than)` — FileStore records with `origin = SKILL_BUNDLE`, `created_at < now() - older_than`, whose IDs are not referenced by any `skill.bundle_file_id`.
- [ ] Implement `_aged_soft_deleted_skills(db, older_than)` — `Skill` rows with `deleted_at IS NOT NULL AND deleted_at < now() - older_than`.
- [ ] Add beat schedule entry. Confirm `expires=3600` is set.
- [ ] Unit test: orphan blob older than 14 days → deleted.
- [ ] Unit test: skill with `deleted_at` older than 14 days → blob deleted AND row hard-deleted.
- [ ] Integration test: soft-delete a skill, run sweep immediately → blob NOT deleted, row still present with `deleted_at` set; advance time by 15 days → run sweep → blob deleted, row gone.

---

## 17. Testing

### Context
Per `CLAUDE.md`: prefer external-dependency unit tests when mocking is needed; prefer integration tests for end-to-end; reserve unit tests for complex isolated modules (validator). Don't over-test.

### Proposed Solution

**External-dependency unit tests** — `backend/tests/external_dependency_unit/skills/`:
- `test_skills_lifecycle.py`:
  - Upload valid bundle → 200; `skill` row created; bundle blob in FileStore.
  - Upload invalid bundle (each failure mode) → 4xx with reason; no row, no blobs.
  - Replace bundle → row updated; old blobs deleted from FileStore.
  - Grant skill to group A → user in A sees it via `GET /api/skills`; user not in A doesn't.
  - Slug rename via PATCH → row updated; uniqueness re-checked.
  - `materialize_skills(...)` for user with 2 granted customs + 2 built-ins → 4 directories + valid `.skills_manifest.json`.
  - Built-in `SKILL.md.template` rendering: placeholders expanded; unknown placeholder left literal with warning logged.

**Integration tests** — `backend/tests/integration/tests/skills/`:
- `test_skill_materialization.py`:
  - Provision Craft session for user with one granted custom + one not-granted, start sandbox, read into it:
    - `.agents/skills/<granted>/SKILL.md` matches uploaded bundle.
    - `.agents/skills/<not-granted>/` doesn't exist.
    - `.agents/skills/<builtin-with-template>/SKILL.md` has placeholders rendered.
    - `.skills_manifest.json` lists materialized skills with `source` discriminator.
    - `AGENTS.md` `{{AVAILABLE_SKILLS_SECTION}}` includes granted skills.
- `test_live_skill_propagation.py`:
  - Start session A, agent reads `.agents/skills/<custom-X>/SKILL.md` (recorded for diff).
  - Admin replaces X's bundle.
  - Wait for the push to land (~3 sec). If kubectl-exec is mocked / blocked in test infra, call `POST /api/sandbox/{sid}/refresh` to trigger the manual refresh path explicitly.
  - Re-read `.agents/skills/<custom-X>/SKILL.md` from session A → matches **new** bundle.
  - In the same conversation, AGENTS.md still reflects the original inventory.
  - Resume session A (snapshot + restore) → AGENTS.md regenerated → new inventory visible.
- `test_snapshot_excludes_skills.py`:
  - Pause session A. Inspect snapshot tarball — confirm no `/skills/` content.
  - Resume → `.agents/skills` is a symlink to `/skills/` and resolves to current admin state.
- `test_multi_tenant_isolation.py`:
  - Two tenants both create custom skill `deal-summary` → both succeed, isolated.

**Unit tests** — `backend/tests/unit/onyx/skills/`:
- `test_bundle.py`:
  - `validate_custom_bundle` rejects each failure mode.
  - `validate_custom_bundle` accepts known-good fixture.
  - `compute_bundle_sha256` deterministic across timestamp differences.
  - Icon byte sniff rejects `.png` with non-PNG magic bytes.

**Manual smoke (pre-merge checklist):**
- `/admin/skills` lists built-ins + customs.
- Upload custom with Org-wide visibility; start session as another user; skill materialized.
- Re-upload bundle; old session unchanged; new session has new bundle.
- Rename slug; new session uses new slug; resumed old session retains old slug.
- Soft-delete skill; running session unaffected; new session doesn't see it.
- Inline mention indicator appears when agent reads `SKILL.md` in a test session.

### Considerations / Tradeoffs / Decisions
- **Heavy on external-dependency unit tests.** They exercise the FastAPI route + DB + FileStore + access logic together with minimal mocking — the right granularity for the bulk of this system.
- **Integration tests focused on the sandbox boundary.** Where the universal layer meets the actual filesystem inside the pod is the highest-value E2E surface.
- **No load test for the validator.** Bundle uploads are rare, admin-only, and capped at 100 MiB. Concurrency is not a concern.

### Todos
- [ ] Create `backend/tests/external_dependency_unit/skills/` directory and test file.
- [ ] Create `backend/tests/integration/tests/skills/` directory and test files.
- [ ] Create `backend/tests/unit/onyx/skills/` directory and test file.
- [ ] Create test fixtures:
  - [ ] A valid sample skill bundle zip.
  - [ ] Variant bundles for each validation failure mode.
- [ ] Ensure all tests run cleanly with `pytest -xv` and the documented `dotenv` patterns in `CLAUDE.md`.
- [ ] Run the manual smoke checklist before merging.

---

## 18. Security model

### Context

A skill bundle ships arbitrary files into `.agents/skills/<slug>/` and the agent invokes scripts in `scripts/` when it follows `SKILL.md`. **A malicious bundle can run arbitrary code inside every user's Craft session that has access to the skill, every time, automatically, until the grant is revoked.** This is bounded by who can upload — only admins — but admin accounts get phished, admins make mistakes, and orgs sometimes have rogue insiders. Worth being explicit about the trust model rather than discovering it in an incident review.

### Threat model

Skill upload is a **privileged action in V1** — admin RBAC bounds who can introduce executable code. This bound goes away when user-authored skills land in V1.5 (see §19); the threat model rewrites at that point to include "any tenant user can author skills that run in other users' sessions" as a first-class attacker. Below covers V1 only.

The threat actors, in rough order of likelihood:

1. **Compromised admin account** — credentials phished or session hijacked. Most realistic entry path.
2. **Confused admin** — uploads a bundle from an untrusted source (someone Slack-DM'd them a `deal-summary.zip`). Historically common in plugin ecosystems.
3. **Insider with grants permission** — rare but real. Same blast radius as #1.
4. **Supply-chain via shared/community skills** — out of scope for V1; on the future-roadmap.

### Trust boundaries

| Boundary | Enforced by | Purpose |
|---|---|---|
| Upload | Admin RBAC on `/api/admin/skills/custom` | Only admins can introduce code |
| Network + secrets | **Interception layer** (see `interception.md`) | Default-deny external egress; secrets injected server-side, never enter the sandbox; writes to upstream services require approval |
| Process / host | Sandbox pod (Kubernetes) | Containment if the script tries to escape |
| Tenant data | Schema-per-tenant + FileStore tenant-prefix | Isolation between customers |

### Controls in place

**From the interception layer** (cross-reference: `docs/craft/features/interception.md`):
- Sandbox egress goes through Onyx proxy; direct external egress blocked.
- Sandbox image trusts Onyx CA; non-proxy egress fails TLS.
- Per-request classification (read / write / destructive / unknown) against `CraftEgressPolicy`.
- Secrets injected server-side; sandbox never sees raw tokens.
- UNKNOWN classification → approval required by default.

**From the skills system itself:**
- Bundle validator blocks symlinks, path traversal, oversized files, `.template` files.
- Admin-only upload route.
- Per-tenant blob isolation via FileStore prefixing.
- Audit trail on each `skill` row: `author_user_id`, `bundle_sha256`, `created_at`, `updated_at`.

**From the sandbox (must be verified — see checklist below):**
- Pod runs as non-root, dropped capabilities, read-only rootfs.
- Resource limits set.
- IMDSv2 with `httpPutResponseHopLimit: 1` (if AWS).
- No service-account token mount unless required.
- IRSA scoped per-session, not tenant-wide.

### Asks of the interception layer

Two specific decisions in the interception design materially change the residual risk for skills. Both are cheap; both close the largest remaining exfil vectors.

1. **Deny all writes (POST / PUT / PATCH / DELETE) to non-classified domains.** The current draft says "non-secret internet access defaults to pass-through" — that leaves a clean exfil path through webhook collectors, paste sites, and any attacker-controlled public endpoint. Allow GET to non-classified domains (skills legitimately fetch docs, public APIs), but deny writes by default. Exfil requires write; reading the open internet does not.
2. **Approval required for any write within a classified service, not just destructive ones.** A skill granted the Linear integration shouldn't be able to silently post a comment containing exfiltrated data. Treat non-destructive writes (comments, draft creation) the same as destructive ones for approval purposes. The classifier already knows the operation kind — this is a policy choice, not new infrastructure.

These two together collapse the realistic exfil surface to side channels (timing, allowed read patterns) and prompt injection — neither of which are fully addressable, but both are far harder than `curl webhook.site`.

### Known residual risks (V1 accepts these explicitly)

1. **Prompt injection via SKILL.md.** The agent reads SKILL.md as instructions. A malicious bundle can override agent behavior across every session materializing the skill. Mitigated only by approval gates on writes + admin review of SKILL.md content (visible in the detail drawer). Not fully fixable at V1.
2. **Confused-deputy via legitimate grants.** A skill calling `api.linear.app` *as the user* can read everything that user can read in Linear. Even with the "writes require approval" tightening, the read scope of allowed services is the user's full scope. Mitigation is fine-grained per-skill scope declarations — deferred to V2.
3. **Workspace persistence after skill delete.** The skill itself stops being readable on next refresh (typically within seconds), but files the skill *wrote* into the session workspace (e.g. `pptx`-generated decks) persist across snapshot/resume. Admin delete modal must call this out.
4. **Side-channel exfil through allowed reads.** Timing, query patterns, request sizes. Not addressable without significant infrastructure.
5. **Sandbox escape (defense in depth gap).** If a container-escape vuln exists, all network controls are bypassed. Why sandbox hardening is non-negotiable regardless of network posture.

### Audit & forensics

Invocation audit log — write one event per SKILL.md read by an agent:

```
(tenant_id, session_id, user_id, skill_id_or_slug, source: "builtin"|"custom",
 bundle_sha256, opened_at)
```

Surface in admin UI:
- Per-skill detail drawer: "Used N times this week across M users" with drill-down.
- Per-session activity log (already exists for OpenCode events) flags which skills were read.

Forensics value: a malicious skill is detectable within hours of activation if anyone watches the log. Anyone exfiltrating via approved writes leaves an approval trail. Anyone running scripts that hit unusual read patterns shows up in egress logs.

### Sandbox hardening verification checklist

To be confirmed **before merging V1 implementation** (not before merging this design doc):

- [ ] Pod `securityContext.runAsNonRoot: true`.
- [ ] Pod `securityContext.readOnlyRootFilesystem: true` (with explicit writable mounts for `/workspace`, `/tmp`).
- [ ] Container `capabilities.drop: [ALL]`.
- [ ] Resource limits set on `cpu` and `memory`.
- [ ] AWS deployments: IMDSv2 enforced with `httpPutResponseHopLimit: 1`.
- [ ] `automountServiceAccountToken: false` unless the sandbox specifically needs Kubernetes API access (it shouldn't).
- [ ] IRSA role on `file-sync` sidecar scoped to one S3 prefix per session, not the whole tenant bucket. Confirmed against current IAM policy.
- [ ] No environment variables in the sandbox carry secrets (secrets path is interception, not env).
- [ ] Pod network egress only routes through the Onyx interception proxy (NetworkPolicy denies direct egress).

### Admin UI implications

The upload modal gets a one-line trust banner (already noted in §13 mockup updates) framing the threat correctly under the interception model:

> ⚠ **Skills run inside your users' Craft sessions with the integrations they have approved.** Only upload skills from sources you trust. Anyone with access to a skill executes its code when the agent uses it.

The delete confirmation modal gains a line about workspace persistence:

> Files this skill wrote to user workspaces remain there until the sessions end. The skill code itself will no longer run in new sessions.

### Deferred security work

Tracked in §19 alongside other deferred items, but worth naming here:

- **Two-person upload approval** for sensitive skills (V1.5, enterprise feature).
- **Per-skill permission declarations** (network: none/allowlist; fs: read-only; integrations: explicit allowlist) — aligns with the future MCP-tool model.
- **Skill provenance / signing** — only meaningful with a marketplace.
- **Content scanning at upload** — skipped intentionally; trivially bypassable and creates false confidence.

### Todos

- [ ] Cross-reference `docs/craft/features/interception.md` from this section (once that doc is written).
- [ ] Open a tracking issue with the interception team for the two policy asks (deny-non-classified-writes; approval-for-non-destructive-writes).
- [ ] Implement invocation audit log:
  - [ ] New table `skill_invocation_log (id, tenant_id, session_id, user_id, skill_id, slug, source, bundle_sha256, opened_at)`.
  - [ ] Event emitter triggered by the frontend's existing SKILL.md-read pattern match (same source the inline pill uses).
  - [ ] Aggregation query for admin UI: usage counts by skill, by user, by day.
  - [ ] Surface in built-in detail drawer and custom skill detail view.
- [ ] Add workspace-persistence callout to the delete confirmation modal.
- [ ] Update the upload modal warning copy to match the interception-aware framing above.
- [ ] Add the sandbox hardening verification checklist to the implementation PR description; gate merge on completion.

---

## 19. Out-of-scope / deferred

Items knowingly punted; each is reversible without breaking V1.

| Deferred | When | How to add later |
|---|---|---|
| Shared/bundled `SkillRequirement` modules | When 5+ skills depend on the same configuration surface | Today each skill declares its requirements independently — fine when most skills need different things, but if e.g. five skills all need a configured Gemini provider, factor a shared `requirements.py` module that exports `IMAGE_GEN_PROVIDER`, `LLM_PROVIDER`, etc. The data model stays the same; only the registration code dedupes. |
| Per-user skill grants (`Skill__User` table) | When customers report friction with "share with one teammate" via a single-member group workaround, or when user-authored skills (below) land. | Add a `skill__user (skill_id, user_id)` join table, an `Individual users` picker in the grants editor, an OR branch in `list_skills_for_user`'s access query, and `user_ids` to the POST/PUT bodies + `granted_user_ids` to `CustomSkillAdmin`. Migration is additive; no V1 schema disruption. |
| **User-authored skills (third tier)** | V1.5 — when product wants users to author + share their own skills without admin involvement. | Big lift. Adds: (1) user-side `POST /api/skills` upload endpoint with per-user quota + rate limit, (2) `Skill__User` brought back from the cut above for user→user sharing, (3) `source = "user"` value on the manifest discriminator (already designed in V1), (4) skill promotion workflow — new `skill_promotion_request` table, request/approve endpoints, admin pending-promotions UI tab, (5) slug-namespace decision: stay tenant-global (simplest; user-authored shares a namespace with admin customs), or move to per-author namespace (more flexible, more complex), (6) **threat-model rewrite** — user-authored shifts the security model from "bounded by admin RBAC" to "any tenant user can introduce code that runs in other users' sessions." Lateral attacker model becomes first-class; §18 needs a real expansion. Interception layer still bounds external exfil but not within-tenant abuse. (7) User-facing "My skills" page + authorship indicator on the skills panel. ~+4-6 weeks of work after V1 ships. |
| **Skill author tooling** | V1.5 — paired with user-authored skills, but useful for admin-authored skills too. | V1 assumes a developer hand-crafts the zip. V1.5 ships authoring affordances so non-engineers can produce a valid skill: (1) a CLI scaffolder (`onyx-cli skill new <slug>`) that generates SKILL.md template, frontmatter, an example script, and the zip layout, (2) a local validator (`onyx-cli skill validate <path>`) that runs the same Pydantic / slug / file-size / SKILL.md-required checks the server does — same error messages, no upload required, (3) a `--dry-run` upload mode that posts to the server, runs validation, and returns the would-be `OnyxError` without persisting, (4) docs page with the format spec, allowed tools, sandboxing constraints, and a worked example. None of this changes the server schema; it's purely a UX layer for skill authors. ~1-2 weeks once we know what shape user-authored skills take. |
| **Skill audit history** | V1.5 — when the first compliance-driven customer asks, or when we observe admins asking "what changed?" in support tickets. | V1 captures enough on the skill row (`created_at`, `updated_at`, `author_user_id`) to answer most questions; what's missing is a temporal record of mutations — slug renames, grant changes, bundle replacements, deletes. Add: (1) `skill_audit_event (id, skill_id, tenant_id, actor_user_id, event_type, payload jsonb, created_at)` table in the private schema, (2) write path triggered from every mutation endpoint (single helper, ~10 lines), (3) admin UI "Activity" tab on the Skills admin page rendering the events with filtering by skill and by date, (4) retention policy (default 13 months, configurable per tenant). Strictly additive — no V1 schema disruption. Pairs naturally with the existing orphan-cleanup sweep (§16). |
| Per-org built-in toggle (`org_enabled`) | When first customer asks | Add `builtin_skill_org_state (slug, enabled)` table in private schema. Admin UI gains a toggle on built-in rows. Materializer filters by it. |
| Per-session user opt-out / pinning | When skill counts grow | Add `build_session__skill_opt_out (session_id, slug)` table. Materializer subtracts these at session start. Panel gains toggles. |
| AGENTS.md threshold + discovery fallback | When skill counts hit ~50+ | Restore the `BUILD_SKILLS_INLINE_LIMIT` mechanism from `skills.md`. |
| Skill versioning / rollback | When evidence of need | Add `skill_version` table; bundle attaches to version row; `latest_version_id` on `skill`. |
| Persona / Chat consumer | Future project | New consumer adapter under that feature's directory; reuses universal layer. May add its own join table for explicit attachment. |
| In-browser skill editor | UX investment item | Significant new UI surface; out-of-scope for V1. |
| Slug rename history | If customers report confusion | Add `skill_rename_history (skill_id, old_slug, new_slug, changed_at)` table. |
| Skill marketplace, signed skills | Not on near roadmap | Distinct product surface. |
| Cross-skill dependencies | Not needed for V1 set | Bundle format extension; resolver in materializer. |
| Hard delete from admin UI | Engineer-only via DB for now | Add a `DELETE ... HARD=true` route variant later. |

---

## 20. Additional domain reviews (acknowledged, not actioned in V1)

These lenses were considered during planning and intentionally not written up in detail. Each could surface real issues; none rise to "must address before V1." Listed so they're not forgotten — and so a future reviewer can challenge the deferral if their context differs.

- **Reliability & failure modes.** Partial-materialization (one bundle's FileStore read fails mid-session-start), concurrent admin edits without optimistic locking, bundle-replace racing session start, built-in `is_available` raising vs returning False. Spec covers happy paths well; the intermediate states are left to implementation-time judgement.
- **Observability.** Logs, metrics, and traces around materialization are not specified. Materialization runs on every session start, so the right signals (`skill_materialization_duration_seconds`, validation failure counters, etc.) will matter in prod. Plan to add them in the implementation PR rather than the design.
- **Performance at scale.** Per-session FileStore reads grow with custom-skill count; snapshots grow proportionally. Probably fine for V1 expected scale (≤20 customs per tenant). Worth a back-of-envelope check during load testing rather than a design constraint.
- **Accessibility.** Admin UI mockups inherit Onyx tokens but haven't been audited for WCAG AA contrast, modal focus management, screen-reader semantics, or keyboard navigation through the visibility radio + chip pickers. Should be a checklist item during frontend implementation, not a design-time concern.
- **DX for built-in authors.** Adding a built-in is "drop a directory + add a `register()` call + redeploy." Clean, but the local iteration loop (rendering `SKILL.md.template` with a fake render context, smoke-testing scripts) is undocumented. Address in a contributor doc when the second built-in lands.
- **Compliance / data handling.** Retention of soft-deleted skill rows is indefinite (only blobs are swept). GDPR user-deletion sets `author_user_id` to NULL but keeps the skill (org-owned, intentional). SOC 2 audit trail for upload/replace/delete events should land in Onyx's existing audit log infra rather than a parallel store — confirm during implementation.
- **Cross-feature naming hygiene.** Skills are not Tools (the persona-attached `Tool` model). Worth one doc-comment in the universal layer pointing this out so future contributors don't conflate them.

If any of these turn out to actually block V1, lift them into a numbered section. Until then, they're tracked here for posterity.

---

## 21. Implementation plan — prioritized phases

> **The live task board lives in [`TODOS.md`](./TODOS.md)** — claim/status/owner per task, agent-coordination conventions, decisions log. This section is the strategic rollup: critical path, dependencies, calendar, what to cut if behind. Don't track day-to-day status here.

Six phases. Each has a **goal**, **dependencies**, and rough **effort** sizing (S = <1 day, M = 2–5 days, L = 1+ week).

**Critical path:** Phase 1 → 2 → 3 → 6. Phase 4 (Admin UI) and Phase 5 (Security ops) run in parallel after Phase 2. Ship Phases 1–3 alone and you have a CLI-operable skills system — engineers can upload via `curl`, users get skills in sessions. Phase 4 makes it admin-usable; Phase 5 makes it productionizable.

---

### Phase summaries

| Phase | Goal | Effort | Depends | Spec sections |
|---|---|---|---|---|
| **1. Foundation** — universal primitive | DB + registry + validator + materializer + DB ops compile and unit-test cleanly. No HTTP, no sandbox wiring. | M | — | §2, §3, §4, §5, §6 |
| **2. Operability** — API surface | Full CRUD via `curl`. `GET /api/admin/skills` returns `available + requirements`. No admin UI, no sandbox wiring yet. | M | Phase 1 | §7 |
| **3. Craft consumer wiring** | Skills materialize into real sandboxes. End-to-end works for any user, even without admin UI. K8s + local backends. AGENTS.md rewrite. Dockerfile updated. | M | Phase 1 | §4, §8, §9, §10 |
| **4. Admin UI** | `/admin/skills` page with list, upload, grants, replace bundle, delete, built-in detail drawer. | L | Phase 2 endpoints stable | §13 |
| **5. Security & operations** | Feature flag, sandbox hardening verification, interception-team coordination, orphan-blob sweep, per-session skills UI in Craft. | M | — (parallel with 3/4) | §11, §15, §16, §18 |
| **6. Polish, rollout, ship** | Snapshot-excludes-skills verification, multi-tenant isolation test, manual smoke, deploy sequence + flag flip. | S–M | Phase 3 + Phase 5 | §12, §14, §17, §15 |

For task-level state — what's `[TODO]` vs `[WIP]` vs `[REVIEW]` vs `[DONE]`, who owns what, what's blocked — see **[`TODOS.md`](./TODOS.md)**.

---

### Suggested calendar (if one engineer, full-time)

| Week | Phases |
|---|---|
| 1 | Phase 1 (foundation) |
| 2 | Phase 2 (API) + start Phase 3 |
| 3 | Phase 3 (consumer wiring) + Phase 5 prep (file interception ticket, audit hardening) |
| 4 | Phase 4 (admin UI core) |
| 5 | Phase 4 (admin UI polish) + Phase 6 prep |
| 6 | Phase 6 (rollout) — flag-off ship → soak → flag-on |

Faster path (two engineers):
- Backend eng: Phase 1 → 2 → 3 → 6.
- Frontend eng: starts Phase 4 once Phase 2 endpoints stabilize (~end of week 1).
- Phase 5 work is small enough to interleave.

---

### What to cut if time is tight

In rough order of "cuttable first":

1. **Invocation audit log** (Phase 5 stretch) — high value but defer to V1.5.
2. **Built-in detail drawer** (Phase 4) — engineers can read source dirs directly.
3. **`SkillRequirement` system** (Phase 1, §4) — ship `image-generation` always-available with a runtime-error caveat. Lose the clean "Needs setup" UX but cut a chunk of work. **Only acceptable** if the interception layer is the safety net.
4. **Per-skill content endpoint** (`/api/build/sessions/{id}/skills/{slug}/content`, Phase 3) — SKILL.md preview drawer in panel; defer to V1.5.
5. **Local sandbox backend skills materialization** — if Kubernetes is the only deploy target for V1, defer the local-backend changes.

Don't cut, even if tempted:
- Bundle validator security rules (path traversal, symlinks, size caps) — these are load-bearing.
- Sandbox hardening verification (§18) — non-negotiable.
- Snapshot fidelity (§12) — protocol contract.
- Feature flag staged rollout (§15) — avoids the "no skills available" gap during deploy.

---

## Quick reference

**Public Python surface (`backend/onyx/skills/__init__.py`):**

```python
from .registry      import BuiltinSkillRegistry, BuiltinSkill
from .bundle        import validate_custom_bundle, compute_bundle_sha256, InvalidBundleError
from .materialize   import materialize_skills, SkillRenderContext, SkillsManifest, SkillManifestEntry
from .render        import render_template_placeholders
```

**HTTP routes added:**
- `/api/admin/skills` (GET)
- `/api/admin/skills/custom` (POST)
- `/api/admin/skills/custom/{id}` (PATCH, DELETE)
- `/api/admin/skills/custom/{id}/bundle` (PUT)
- `/api/admin/skills/custom/{id}/grants` (PUT)
- `/api/skills` (GET)
- `/api/build/sessions/{id}/skills` (GET)
- `/api/build/sessions/{id}/skills/{slug}/content` (GET)

**Tables added (private schema):**
- `skill`
- `skill__user_group`

**FileOrigin values added:**
- `SKILL_BUNDLE`

**Files modified (key sites):**
- `backend/onyx/db/models.py` — two new tables.
- `backend/onyx/configs/constants.py:373` — `FileOrigin` enum.
- `backend/onyx/main.py` — registration call.
- `backend/onyx/server/features/build/sandbox/manager/directory_manager.py:325` — drop `setup_skills`, drop `_skills_path`.
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:1338` — replace symlink block with tarball-into-pod.
- `backend/onyx/server/features/build/sandbox/util/agent_instructions.py:267` — **delete** `build_skills_section` + `_skills_cache` entirely. Remove `{{AVAILABLE_SKILLS_SECTION}}` from template. OpenCode's native `skill` tool handles inventory.
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile:99` — drop `COPY skills/`, drop `mkdir`.

**On-disk built-in source** (unchanged):
`backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/<slug>/`
