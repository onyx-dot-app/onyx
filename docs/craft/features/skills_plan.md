# Skills V1 — PRD & Implementation Spec

**Status**: design · **Source plan**: `docs/craft/features/skills.md` · **Owner**: Roshan

This document is structured so implementation can begin section-by-section with minimal further design. Each section follows the same shape:

1. **Context** — what is the ask, why does it exist, what problem does it solve.
2. **Proposed Solution** — the V1 design.
3. **Considerations / Tradeoffs / Decisions** — what we considered, what we rejected, what is intentionally deferred.
4. **Todos** — concrete, file-level engineering tasks.

> **Three invariants the whole design respects:**
>
> 1. **Sessions are skill-immutable after start.** Mutations affect new sessions only.
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

### Considerations / Tradeoffs / Decisions
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

### Considerations / Tradeoffs / Decisions
- **Why a separate `backend/onyx/server/features/skills/api.py` rather than inlining endpoints into the build feature.** Customers will integrate against `/api/admin/skills`. Moving that path later (when Persona/Chat adopts) is a breaking change. Putting it at the universal layer on day one is cheap.
- **Why `BuiltinSkillRegistry` is a singleton, not DB-backed.** Built-ins are code-defined; their identity moves with the deploy. Persisting them adds a seeder, hash tracking, and a registry-vs-DB-drift failure mode for zero benefit.
- **Why the panel data source is a Craft-specific endpoint, not the universal `/api/skills`.** Because of snapshot fidelity (§12), a resumed session's skills can diverge from the user's current grants. The panel must reflect what's *actually in the session*, which lives in `.skills_manifest.json` — read via a session-scoped endpoint that the build feature owns.

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

    owner_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled:   Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted:   Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
        Index("ux_skill_slug", "slug", unique=True),
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
- Per-tenant unique (via schema isolation; no `tenant_id` column).
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
  - [ ] `list_skills_for_user(user, db) -> list[Skill]` — public OR group-grant (mirror `fetch_persona_by_id_for_user` at `backend/onyx/db/persona.py:81`, minus the direct-user-grant branch).
  - [ ] `fetch_skill_for_user(skill_id, user, db) -> Skill | None`.
  - [ ] `fetch_skill_for_admin(skill_id, db) -> Skill | None` — no access filter.
  - [ ] `list_skills_for_admin(db) -> list[Skill]` — no access filter.
  - [ ] `create_skill(slug, name, description, bundle_file_id, bundle_sha256, manifest_metadata, is_public, owner_user_id, db) -> Skill`.
  - [ ] `replace_skill_bundle(skill_id, new_bundle_file_id, new_sha256, new_manifest_metadata, db) -> Skill` (returns old_bundle_file_id so caller can delete the blob after commit).
  - [ ] `patch_skill(skill_id, slug=None, name=None, description=None, is_public=None, enabled=None, db) -> Skill` (partial update).
  - [ ] `replace_skill_grants(skill_id, group_ids, db) -> None` (atomic: delete + insert in one transaction).
  - [ ] `delete_skill(skill_id, db) -> str` — soft-delete; returns `bundle_file_id` for blob deletion.

---

## 4. Built-in skill registry

### Context
Built-in skills are on-disk directories. We need a way for each feature that ships built-ins (today only the build feature) to register them with the universal layer at app boot. We also need this registration to be cheap to extend later (e.g. adding capability checks when the interception layer lands).

### Proposed Solution

A process-wide singleton populated at app boot. Each registration captures a `(slug, source_dir, name, description, requirements)` tuple — name/description are read from the source dir's `SKILL.md` frontmatter at registration time and cached. `requirements` declare the org-level dependencies the skill needs to run (e.g. a configured Gemini provider for `image-generation`).

```python
# backend/onyx/skills/registry.py

@dataclass(frozen=True)
class SkillRequirement:
    key: str                                 # stable id, e.g. "image_generation_provider"
    name: str                                # human label, e.g. "Image generation provider"
    description: str                         # what's missing + where to set it up
    configure_url: str                       # e.g. "/admin/configuration/image-generation"
    check: Callable[[Session], bool]         # returns True if satisfied; cheap

@dataclass(frozen=True)
class BuiltinSkill:
    slug: str
    source_dir: Path
    name: str
    description: str
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
3. `customs = list_skills_for_user(user, db_session)` — single SQL query, public-OR-group-OR-direct.
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
| `DELETE` | `/api/admin/skills/custom/{id}` | — | Soft-delete (`deleted=true`) |

**User endpoints** (`/api/skills` — authenticated user):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/skills` | Skills accessible to current user (forward-looking, for fresh sessions) |

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
    owner_user_id: UUID | None
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
  - [ ] `DELETE /api/admin/skills/custom/{id}` — call `delete_skill(...)`. Soft-delete; don't delete blobs (sweep handles it after retention).
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

## 9. Sandbox delivery (local + Kubernetes)

### Context
After the materializer writes a staging dir, the sandbox manager needs to put those files at `.agents/skills/` inside the session. The two backends (local/docker and Kubernetes) have different mechanisms.

### Proposed Solution

**Kubernetes:** tar the staging dir, stream into pod via `kubectl exec ... tar xf -`.

```python
def _stream_skills_into_pod(self, pod_name: str, staging_dir: Path, session_path: str) -> None:
    target = f"{session_path}/.agents/skills"
    self._kubectl_exec(pod_name, ["mkdir", "-p", target])

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        tar.add(staging_dir, arcname=".")
    tar_buf.seek(0)

    self._kubectl_exec_stdin(
        pod_name,
        ["tar", "xf", "-", "-C", target],
        stdin=tar_buf.read(),
    )
```

This replaces the existing block at `kubernetes_sandbox_manager.py:1338-1340`:

```python
# REMOVE (legacy code currently in the file):
if [ -d /workspace/skills ]; then
    mkdir -p {session_path}/.opencode
    ln -sf /workspace/skills {session_path}/.opencode/skills
fi

# REPLACED BY (after the rest of the setup_script runs):
self._stream_skills_into_pod(pod_name, staging_dir, session_path)
shutil.rmtree(staging_dir, ignore_errors=True)
```

The `_kubectl_exec_stdin` helper already exists (used by snapshot restore — same pattern).

**Local / Docker:** copy directly into the mounted workspace.

```python
def _setup_skills_local(self, staging_dir: Path, session_path: Path) -> None:
    skills_dest = session_path / ".agents" / "skills"
    skills_dest.parent.mkdir(parents=True, exist_ok=True)
    if skills_dest.exists():
        shutil.rmtree(skills_dest)
    shutil.copytree(staging_dir, skills_dest)
    shutil.rmtree(staging_dir, ignore_errors=True)
```

This replaces the existing `directory_manager.setup_skills(...)` call sequence.

**Dockerfile change:**
```dockerfile
# REMOVE (Dockerfile:99):
COPY skills/ /workspace/skills/

# REMOVE (around the same area):
RUN mkdir -p /workspace/skills
```

The on-disk source at `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/` **stays** — it's now read at runtime from the api_server / Celery host FS, not baked into the sandbox image.

**Why `.agents/skills/` and not `.opencode/skills/`?** OpenCode's skill-discovery walks the project tree and reads SKILL.md from multiple conventional locations: `.opencode/skills/`, `.agents/skills/`, and `.claude/skills/` (per [OpenCode docs](https://opencode.ai/docs/skills/)). Using `.agents/skills/` makes our contract agent-runtime-agnostic — if Onyx ever swaps OpenCode for Codex or a multi-runtime setup, the materialized path doesn't need to change. The current `.opencode/skills/` symlink in `kubernetes_sandbox_manager.py:1338` is being removed (legacy code shown above).

### Considerations / Tradeoffs / Decisions
- **Tarball-into-pod vs `kubectl cp`.** The existing snapshot-restore code already uses the tar-over-exec pattern. Reusing it gives us the same robustness profile.
- **Why copy vs symlink for local backend.** The new model materializes per-session content (with user-specific template rendering). Symlinks can't deliver per-session content. Copy is the only option.
- **`staging_dir` cleanup.** Always delete after delivery (success or failure). Don't leak temp directories.
- **What if the sandbox manager can't deliver (e.g. pod isn't ready)?** This is a session-setup failure — propagate the exception. The session won't start; the user sees an error. Same failure mode as snapshot-restore today.

### Todos
- [ ] Implement `_stream_skills_into_pod(pod_name, staging_dir, session_path)` in `KubernetesSandboxManager`. Place it near the existing snapshot-restore helpers.
- [ ] Replace the `ln -sf /workspace/skills` block in `kubernetes_sandbox_manager.py:1338-1340` with a call to `_stream_skills_into_pod(...)` after the setup script runs. Pass `staging_dir` from the new materialization step.
- [ ] Implement `_setup_skills_local(staging_dir, session_path)` in the local sandbox manager.
- [ ] Replace `directory_manager.setup_skills(...)` callsites with `_setup_skills_local(...)`.
- [ ] Update the Kubernetes session-setup flow to call `materialize_for_session(...)` early, before the setup script, and pass `staging_dir` through.
- [ ] Update the local session-setup flow similarly.
- [ ] Edit `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile`:
  - [ ] Remove `COPY skills/ /workspace/skills/` (line ~99).
  - [ ] Remove `mkdir -p /workspace/skills`.
- [ ] Add a feature flag `SKILLS_MATERIALIZATION_V2_ENABLED` for staged rollout (see §15).
- [ ] Update existing integration tests for sandbox setup that may reference the old skills path.

---

## 10. AGENTS.md generation

### Context
The agent's system prompt currently has a `{{AVAILABLE_SKILLS_SECTION}}` placeholder, filled by `build_skills_section(skills_path)` in `agent_instructions.py:267`. It scans the symlinked skills directory once per process (`_skills_cache`) and inlines every skill it finds. We need to replace that with a per-session read from the materialized manifest, and remove the cache.

### Proposed Solution

New implementation:

```python
def build_skills_section(skills_dir: Path) -> str:
    manifest_path = skills_dir / ".skills_manifest.json"
    if not manifest_path.exists():
        return "No skills available."

    manifest = SkillsManifest.model_validate_json(manifest_path.read_text())
    all_skills = manifest.builtin + manifest.custom
    if not all_skills:
        return "No skills available."

    lines = [
        "You have these skills available under `.agents/skills/<slug>/`. "
        "Read the relevant SKILL.md before starting work that the skill covers.",
        "",
    ]
    for entry in all_skills:
        lines.append(f"- **{entry.slug}**: {entry.description}")
    return "\n".join(lines)
```

No threshold logic, no discovery fallback, no built-in-vs-custom split — all skills inlined uniformly. `agent_instructions.py:481-495` (the templating step) is unchanged; only `build_skills_section` changes.

### Considerations / Tradeoffs / Decisions
- **No threshold in V1.** Expected counts are <20 per tenant. Inlining 20 entries × ~150 chars ≈ 3000 chars ≈ 750 tokens. Trivial on modern contexts.
- **Source not surfaced to the agent.** Built-in vs custom is irrelevant to invocation — the agent reads `SKILL.md` either way. The panel shows the badge to humans; AGENTS.md doesn't.
- **Cache removal.** The existing `_skills_cache` keyed on `skills_path` returns stale data once skills are per-session. Removing it is required for correctness.

### Todos
- [ ] Rewrite `build_skills_section(skills_dir)` in `backend/onyx/server/features/build/sandbox/util/agent_instructions.py:267-296`.
- [ ] Delete `_skills_cache: dict[str, str]` and `_skills_cache_lock` (top of the same file).
- [ ] Delete `_scan_skills_directory(...)` if it's unused after the rewrite.
- [ ] Verify callsite at `agent_instructions.py:481` still works (signature unchanged).
- [ ] Confirm `build_skills_section` is called with the materialized skills dir, not the source dir.

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
  - [ ] `web/src/app/craft/.../SkillsPanel.tsx` — fetches `/api/build/sessions/{id}/skills`, renders the list.
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

## 12. Snapshot fidelity

### Context
Craft sessions can be paused and resumed days later. The question is: when a session resumes, should it see its original skills (snapshot-frozen) or current skills (re-materialized from current grants)? The decision affects materializer behavior, snapshot bundle contents, and admin UX.

### Proposed Solution

**Sessions are skill-immutable after start.** The session's snapshot includes `.agents/skills/` verbatim — bundles, manifest, AGENTS.md fragment, everything. On resume, the snapshot is restored as-is; the materializer is not re-run.

Behavioral implications:
- Admin uploads a new skill → existing/paused sessions don't see it.
- Admin revokes a grant → existing session still has the skill.
- Admin renames a slug → existing sessions retain the old slug.
- Admin deletes a skill → existing sessions still have it.
- Capability changes (e.g. env var unset) don't affect resumed sessions; agent may hit a runtime failure if it tries to use a now-broken skill.

Admin UI must surface this on every mutation. Confirmation modals on delete / replace bundle / rename / revoke grant must say:

> "This change applies to **new sessions only**. Existing and paused sessions continue with the current version until they end."

### Considerations / Tradeoffs / Decisions
- **Snapshot fidelity vs re-materialize-on-resume.** Considered both. Re-materialize is more "always current" but breaks the "session is your workspace" mental model — admin changes can silently alter resumed work. Frozen is more predictable.
- **Snapshot size impact.** Each snapshot now includes the materialized skills (~few MB per custom skill bundle). V1 expects ≤10 customs per tenant; impact is bounded. If snapshot sizes become a problem, V2 can deduplicate skills across snapshots (content-addressed storage in the snapshot mechanism) — but that's not a V1 concern.
- **Capability flips and resumed sessions.** If `GEMINI_API_KEY` is unset and a paused session has `image-generation` materialized, the agent will try and fail. Acceptable for V1 — rare scenario, recoverable error.
- **No kill switch.** If an admin uploads a buggy/malicious skill and revokes the grant, running sessions keep using it. V1 accepts this; a kill switch is a separate feature (per-session blocklist applied at read-time inside the sandbox).

### Todos
- [ ] Confirm snapshot manager (`SnapshotManager` / s5cmd flow) already includes `.agents/skills/` in the tarball — likely yes since it's just part of the workspace, but verify in `backend/onyx/server/features/build/sandbox/manager/snapshot_manager.py`.
- [ ] If not, ensure `.agents/skills/` is included in snapshot tar.
- [ ] On resume path: verify materializer is **not** called. The skills should arrive purely via snapshot restore.
- [ ] Add "applies to new sessions only" copy to all mutation confirmation modals in the admin UI.
- [ ] Add a top-level invariant note in `backend/onyx/skills/__init__.py` module docstring: "Sessions are skill-immutable after start."
- [ ] Integration test: pause a session, change skill state, resume → verify snapshot contents unchanged.

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

Submit → `POST /api/admin/skills/custom` (multipart). Success: modal closes, skill appears in list. Validation failure: inline error under offending field with reason from `OnyxError`.

#### 13.3 Edit / Replace bundle / Grants
On a custom skill row:
- **Edit** (slug, name, description, visibility) → inline form or modal → `PATCH /api/admin/skills/custom/{id}` then `PUT .../grants` if visibility changed.
- **Replace bundle** → drag-and-drop new zip in a modal with confirmation copy → `PUT /api/admin/skills/custom/{id}/bundle`.
- **Manage grants** → reuses the visibility picker → `PUT /api/admin/skills/custom/{id}/grants`.

All mutation modals include the "applies to new sessions only" callout.

#### 13.4 Delete
Soft-delete confirmation modal:
> "Delete `<name>`? This removes it from new sessions. Sessions currently using it will keep the skill until they end. This action can be reversed by an engineer in the database."

Submit → `DELETE /api/admin/skills/custom/{id}`. Row disappears from list. Hard delete is not a V1 admin action.

#### 13.5 Component reuse
Visibility picker (radio + group + user multi-select) is reused across upload modal, edit modal, and standalone grants editor. Build it once as a shared component.

### Considerations / Tradeoffs / Decisions
- **Unified list vs two sections.** Considered separating built-ins and customs into two sections. Chose unified with badges — ChatGPT-Apps-style — for cohesion. The absence of an action menu signals "this isn't user-controllable" without needing a second section.
- **Frontmatter pre-fill is convenience, not authority.** Admin can edit pre-filled values before submitting. After submit, the DB row is the source of truth.
- **No "default visibility" — admin chooses at upload time.** Silent defaults create accidental over- or under-sharing. Forcing a choice adds one click per upload (low friction).
- **No audit log in V1.** "Who uploaded what when" is satisfied by `created_at`/`updated_at`/`owner_user_id`. Detailed change history (slug renames, grant edits) is V2.
- **No bulk operations.** "Grant skill X to N groups at once" is the picker. "Delete N skills" isn't a workflow we've heard demand for.

### Todos
- [ ] Create `web/src/app/admin/skills/page.tsx` — list view shell.
- [ ] List components:
  - [ ] `web/src/app/admin/skills/SkillsList.tsx` — table renderer.
  - [ ] `web/src/app/admin/skills/SkillRow.tsx` — single row with conditional action menu.
  - [ ] `web/src/app/admin/skills/SourceBadge.tsx` — Platform/Custom badge.
  - [ ] `web/src/app/admin/skills/BuiltinDetailDrawer.tsx` — read-only drawer for built-in rows.
- [ ] Upload modal:
  - [ ] `web/src/app/admin/skills/UploadSkillModal.tsx` — file picker, fields, visibility picker.
  - [ ] Client-side frontmatter pre-fill from selected zip (use a zip-reading lib like `jszip`).
- [ ] Edit / replace / grants:
  - [ ] `web/src/app/admin/skills/EditSkillModal.tsx`.
  - [ ] `web/src/app/admin/skills/ReplaceBundleModal.tsx` with "new sessions only" copy.
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
Weekly Celery beat task:

```python
# backend/onyx/background/celery/tasks/skills/tasks.py

@shared_task(name="cleanup_orphaned_skill_blobs")
def cleanup_orphaned_skill_blobs() -> None:
    """Defensive sweep for FileStore blobs with origin SKILL_BUNDLE
    older than 14 days that no skill row references."""
    with get_session_with_current_tenant() as db:
        for blob in _stale_skill_blobs(db, age_days=14):
            file_store.delete_file(blob.file_id)

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
- `DELETE /api/admin/skills/custom/{id}`: soft-delete only; blobs stay for now. **The sweep is the path that eventually deletes blobs for soft-deleted skills.** (Set retention based on `deleted_at`-ish logic — see below.)

### Considerations / Tradeoffs / Decisions
- **Soft-delete + sweep vs hard-delete + immediate blob cleanup.** Soft-delete preserves the option for undelete (engineer-only in V1). The 14-day retention before sweep gives a recovery window.
- **Why weekly.** Orphans are rare (only happen on crashes between save + commit). Weekly is conservative; daily would also be fine.
- **`expires=3600` is required** per the `CLAUDE.md` Celery rule.
- **Task name in `name=` rather than auto-derived.** Stable name across refactors so beat scheduling doesn't break.

### Todos
- [ ] Implement `cleanup_orphaned_skill_blobs` in `backend/onyx/background/celery/tasks/skills/tasks.py`.
- [ ] Implement `_stale_skill_blobs(db, age_days)` — query FileStore records with `origin = SKILL_BUNDLE` and `created_at < now() - age_days` whose IDs aren't referenced in `skill.bundle_file_id` (for any non-deleted skill, OR for deleted-skills-older-than-N-days).
- [ ] Add beat schedule entry. Confirm `expires=3600` is set.
- [ ] Unit test: create an orphan blob older than 14 days, run the task, verify deletion.
- [ ] Integration test: create a skill, soft-delete it, verify the blob is NOT deleted immediately; bump created_at to 14+ days ago, run task, verify deletion.

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
- `test_snapshot_fidelity.py`:
  - Start session A with custom skill X. Snapshot.
  - Admin replaces X's bundle.
  - Resume session A → `.agents/skills/X/SKILL.md` matches **original** bundle.
  - Start fresh session B → B has new bundle.
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

Skill upload is a privileged action. The threat actors, in rough order of likelihood:

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
- Audit trail on each `skill` row: `owner_user_id`, `bundle_sha256`, `created_at`, `updated_at`.

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
3. **Workspace persistence after skill delete.** Files a skill writes to `/workspace` survive in session snapshots even after the skill is soft-deleted. The admin delete modal must call this out.
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
| Per-user skill grants (`Skill__User` table) | When customers report friction with "share with one teammate" via a single-member group workaround | Add a `skill__user (skill_id, user_id)` join table, an `Individual users` picker in the admin grants editor, an OR branch in `list_skills_for_user`'s access query, and `user_ids` to the POST/PUT bodies + `granted_user_ids` to `CustomSkillAdmin`. Migration is additive; no V1 schema disruption. |
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
- **Compliance / data handling.** Retention of soft-deleted skill rows is indefinite (only blobs are swept). GDPR user-deletion sets `owner_user_id` to NULL but keeps the skill (org-owned, intentional). SOC 2 audit trail for upload/replace/delete events should land in Onyx's existing audit log infra rather than a parallel store — confirm during implementation.
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
| **6. Polish, rollout, ship** | Snapshot fidelity verification, multi-tenant isolation test, manual smoke, deploy sequence + flag flip. | S–M | Phase 3 + Phase 5 | §12, §14, §17, §15 |

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
- `backend/onyx/server/features/build/sandbox/util/agent_instructions.py:267` — rewrite `build_skills_section`; remove `_skills_cache`.
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile:99` — drop `COPY skills/`, drop `mkdir`.

**On-disk built-in source** (unchanged):
`backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/<slug>/`
