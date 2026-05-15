# Skills — API Implementation Plan

Implementation plan for the FastAPI layer that exposes the existing skills DB primitives. Optimized for parallel execution by a team of subagents.

Companion docs:
- `skills-db-layer-status.md` — what already exists.
- `skills-requirements.md` — what the feature must do.

## 1. Goal

Add `/admin/skills` (admin CRUD) and `/skills` (user read) HTTP endpoints, backed by the existing DB module (`backend/onyx/db/skill.py`), built-in registry (`backend/onyx/skills/registry.py`), and bundle validator (`backend/onyx/skills/bundle.py`). Mutations push bundle bytes into running sandbox pods via `SandboxManager.push_to_sandboxes` (see `docs/craft/features/sandbox-file-push.md`); the FileStore blob is still written for persistence and cold-start hydration.

## 2. Out of Scope

- Extending `SandboxManager` with the push API and per-backend `write_files_to_sandbox` implementation (separate workstream — see `sandbox-file-push.md`).
- Built-in skill source files / registrations (registry exists; registering specific built-ins is a separate workstream).
- Cold-start hydration plumbing in `setup_session_workspace` (owned by the push-primitive workstream).
- ~~Orphan-blob sweep job~~ — resolved: delete/replace endpoints now clean up old blobs inline via `_delete_old_bundle` (best-effort, logs on failure).
- Built-in availability flip push triggers (built-in availability is a function of external state, not an API mutation; sandboxes re-converge on next session start/wakeup).
- `GET /skills/{slug_or_id}` single-skill endpoint (deferred unless a concrete UI need arises; DB layer has `fetch_skill_for_user` ready).
- Front-end work.

### Design decision: built-ins stay in-memory

Built-in skills live in the `BuiltinSkillRegistry` singleton and are **not** seeded to the database. They are merged with DB-backed custom skills at query time in the list endpoints. This was decided because multi-tenant cloud (~20k tenants) makes DB seeding impractical — there is no "iterate all tenants on deploy" path. The in-memory registry is populated once at app boot and shared across tenants.

## 3. File Layout

New files (all under `backend/onyx/server/features/skill/`):

```
backend/onyx/server/features/skill/
├── api.py                   # routers, endpoints
└── models.py                # Pydantic request/response models
```

Plus the skills-side push helpers, co-located with the skills module:

```
backend/onyx/skills/push.py  # build_skills_files_for_user, push_to_pod
```

Plus a new DB helper for sandbox-to-user resolution:

```
backend/onyx/server/features/build/db/sandbox.py   # get_sandbox_user_map(user_ids, db_session) -> dict[UUID, User]
```

`get_sandbox_user_map` queries the sandbox DB for active sandboxes belonging to the given users, returning `{sandbox_id: user}`. This is the caller's responsibility per the push API contract — `SandboxManager` has no DB access.

`build_skills_files_for_user` returns the flat `FileSet` (`dict[str, bytes]`) used as values in the `sandbox_files` mapping passed to `push_to_sandboxes`. `push_to_pod` is the cold-start single-pod helper called from `setup_session_workspace`, calling `get_sandbox_manager().push_to_sandbox(sandbox_id=sandbox_id, ...)`.

Modified files:
- `backend/onyx/main.py` — register the two routers.
- `backend/onyx/db/skill.py` — refactor `patch_skill` to accept `SkillPatch`; add `affected_users_for_skill` and `get_group_ids_for_skill`.

New test files:
- `backend/tests/integration/common_utils/managers/skill.py` — `SkillManager`.
- `backend/tests/integration/common_utils/test_models.py` — `DATestSkill`.
- `backend/tests/integration/tests/skills/test_skills_admin.py`
- `backend/tests/integration/tests/skills/test_skills_user.py`

## 4. Pydantic Models (`models.py`)

Keep them flat and explicit. No `response_model=` on endpoint decorators (per CLAUDE.md); use return-type annotations only.

### Response models

Two-layer pattern: ORM model (or `BuiltinSkill`) -> Pydantic response. There is no intermediate domain model. This matches the Persona/Tool convention used throughout the codebase.

- `BuiltinSkillResponse.from_skill(builtin, db_session)` converts an in-memory `BuiltinSkill` to a serializable response, evaluating the `is_available` callable to a `bool`.
- `CustomSkillResponse.from_model(orm_skill, group_ids)` converts an ORM `Skill` object directly to a response, adding `granted_group_ids`. No intermediate `CustomSkill` domain class exists.

```python
class BuiltinSkillResponse(BaseModel):
    """Thin wrapper — evaluates the is_available callable to a bool."""
    source: Literal["builtin"] = "builtin"
    slug: str
    name: str
    description: str
    is_available: bool
    unavailable_reason: str | None = None

    @classmethod
    def from_skill(cls, skill: BuiltinSkill, db_session: Session) -> "BuiltinSkillResponse":
        return cls(
            slug=skill.slug, name=skill.name, description=skill.description,
            is_available=skill.is_available(db_session),
            unavailable_reason=skill.unavailable_reason,
        )

class CustomSkillResponse(BaseModel):
    """Converts ORM Skill -> API response. Adds granted_group_ids."""
    source: Literal["custom"] = "custom"
    id: UUID
    slug: str
    name: str
    description: str
    is_public: bool
    enabled: bool
    author_user_id: UUID | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    granted_group_ids: list[int] = []

    @classmethod
    def from_model(cls, skill: Skill, group_ids: list[int]) -> "CustomSkillResponse":
        return cls(
            id=skill.id, slug=skill.slug, name=skill.name,
            description=skill.description, is_public=skill.is_public,
            enabled=skill.enabled, author_user_id=skill.author_user_id,
            created_at=skill.created_at, updated_at=skill.updated_at,
            granted_group_ids=group_ids,
        )

class SkillsList(BaseModel):
    builtins: list[BuiltinSkillResponse]
    customs: list[CustomSkillResponse]
```

`CustomSkillResponse` is a standalone `BaseModel` — it reads fields directly from the ORM `Skill` object. `bundle_file_id` is simply not included in the response fields (no need for `Field(exclude=True)`).

`BuiltinSkillResponse` can't extend `BuiltinSkill` because the `Callable` field and `source_dir`/`has_template` internals shouldn't leak. It duplicates the 4 base fields (`slug`, `name`, `description`, `source`) — acceptable for 4 fields.

### Request models

```python
class SkillPatchRequest(BaseModel):
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    enabled: bool | None = None

    def to_domain(self) -> SkillPatch:
        return SkillPatch(**{
            f: getattr(self, f) for f in self.model_fields_set
        })

class GrantsReplace(BaseModel):
    group_ids: list[int]
```

### Domain patch object

Lives in `backend/onyx/db/skill.py` alongside the existing `UNSET` sentinel:

```python
@dataclass(frozen=True, kw_only=True)
class SkillPatch:
    slug: str | UnsetType = UNSET
    name: str | UnsetType = UNSET
    description: str | UnsetType = UNSET
    is_public: bool | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET
```

The endpoint receives `SkillPatchRequest` (Pydantic, `None` = not sent), calls `to_domain()` which uses `model_fields_set` to distinguish "sent" from "not sent", producing a `SkillPatch` (frozen dataclass, `UNSET` = not sent). `patch_skill` in the DB layer receives `SkillPatch` directly — no translation at the boundary.

The existing `patch_skill` function in `db/skill.py` currently takes individual keyword arguments. It should be refactored to accept a `SkillPatch` directly, keeping the DB layer's interface clean.

### Notes on ORM -> response conversion

The DB layer returns ORM `Skill` objects directly — there is no intermediate `CustomSkill` domain class. `CustomSkillResponse.from_model(orm_skill, group_ids)` reads all needed fields (`id`, `slug`, `name`, `description`, `is_public`, `enabled`, `author_user_id`, `created_at`, `updated_at`) from the ORM object. Group grant IDs are fetched separately via `get_group_ids_for_skill(skill_id, db_session)` in `db/skill.py` and passed in.

Listing is non-paginated in V1 (skill counts will be tiny). If/when needed, add `PaginatedReturn[CustomSkillResponse]` per the persona pattern.

## 5. Routes (`api.py`)

```python
admin_router = APIRouter(prefix="/admin/skills")
user_router = APIRouter(prefix="/skills")
```

### Admin endpoints

```python
@admin_router.get("")
def list_skills_admin(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillsList: ...

@admin_router.post("/custom")
def create_custom_skill(
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    is_public: bool = Form(False),
    group_ids: str = Form("[]"),       # JSON-encoded list[int]
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse: ...

@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    patch: SkillPatchRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse: ...

@admin_router.put("/custom/{skill_id}/bundle")
def replace_custom_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse: ...

@admin_router.put("/custom/{skill_id}/grants")
def replace_custom_skill_grants(
    skill_id: UUID,
    body: GrantsReplace,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse: ...

@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None: ...
```

Note: `group_ids` in the create endpoint is a JSON-encoded string (`"[1, 2, 3]"`) parsed server-side, avoiding FastAPI's awkward repeated-form-field semantics for list-typed `Form()` params.

Note: create uses multipart (bundle file upload requires it); patch and grants use JSON bodies.

### User endpoints

```python
@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList: ...
```

## 6. Endpoint Implementation Sketches

Every mutation follows the same shape: validate → write to DB + FileStore → commit → compute affected users → resolve sandbox_ids via `get_sandbox_user_map` → build per-sandbox file sets → push via `push_to_sandboxes`. "Push" is a full snapshot of the user's `mount_path`, so removing a skill = pushing the user's new file dict without that skill.

`affected_users_for_skill(skill, db_session)` (helper in `backend/onyx/db/skill.py` — it queries users and user-group relationships, which per CLAUDE.md must live under `backend/onyx/db/`) returns the set of user IDs (`set[UUID]`) with an active sandbox who should have this skill in their bundle. For visibility/grant transitions, the caller takes the union of the before-and-after sets so users who lost access also get re-pushed (without the skill).

### `POST /admin/skills/custom`

```python
def create_custom_skill(...) -> CustomSkillResponse:
    bundle_bytes = bundle.file.read()
    validate_custom_bundle(bundle_bytes, slug=slug)    # checks size, format, reserved slugs
    sha = compute_bundle_sha256(bundle_bytes)
    try:
        parsed_group_ids: list[int] = json.loads(group_ids)
    except (json.JSONDecodeError, TypeError):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "group_ids must be a JSON array of integers")

    bundle_file_id = filestore.write(bundle_bytes)

    skill = create_skill(
        slug=slug, name=name, description=description,
        bundle_file_id=bundle_file_id, bundle_sha256=sha,
        is_public=is_public, author_user_id=user.id,
        db_session=db_session,
    )
    if parsed_group_ids:
        replace_skill_grants(skill.id, parsed_group_ids, db_session=db_session)
    db_session.commit()

    _push_skill_to_affected_sandboxes(skill, db_session)
    return CustomSkillResponse.from_model(skill, group_ids=parsed_group_ids)
```

### `PATCH /admin/skills/custom/{id}`

PATCH is the one mutation that conditionally pushes — only when visibility or enabled status changed. Slug/name/description changes don't affect which users see the skill, so no push is needed.

```python
def patch_custom_skill(...) -> CustomSkillResponse:
    domain_patch = patch.to_domain()

    before = fetch_skill_for_admin(skill_id, db_session)
    if before is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    # Reject slug change to a reserved built-in slug
    if domain_patch.slug is not UNSET:
        if domain_patch.slug in BuiltinSkillRegistry.instance().reserved_slugs():
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Slug reserved by a built-in skill")

    before_affected = affected_users_for_skill(before, db_session)
    updated = patch_skill(skill_id, patch=domain_patch, db_session=db_session)
    db_session.commit()

    if _visibility_changed(before, updated):
        after_affected = affected_users_for_skill(updated, db_session)
        _push_skills_to_sandboxes(before_affected | after_affected, db_session)

    return CustomSkillResponse.from_model(updated, group_ids=_get_group_ids(skill_id, db_session))
```

`_visibility_changed` is a local helper in `api.py`:

```python
def _visibility_changed(before: Skill, after: Skill) -> bool:
    return (before.is_public != after.is_public
            or before.enabled != after.enabled
            or before.slug != after.slug)
```

### `PUT /admin/skills/custom/{id}/bundle`

```python
def replace_custom_skill_bundle(...) -> CustomSkillResponse:
    bundle_bytes = bundle.file.read()
    skill = fetch_skill_for_admin(skill_id, db_session)
    validate_custom_bundle(bundle_bytes, slug=skill.slug)
    sha = compute_bundle_sha256(bundle_bytes)
    new_file_id = file_store.write(bundle_bytes)

    updated, old_file_id = replace_skill_bundle(
        skill_id=skill_id, new_bundle_file_id=new_file_id,
        new_bundle_sha256=sha, db_session=db_session,
    )
    db_session.commit()

    _push_skill_to_affected_sandboxes(updated, db_session)
    _delete_old_bundle(file_store, old_file_id)
    return CustomSkillResponse.from_model(updated, group_ids=_get_group_ids(skill_id, db_session))
```

### `PUT /admin/skills/custom/{id}/grants`

```python
def replace_custom_skill_grants(...) -> CustomSkillResponse:
    before = fetch_skill_for_admin(skill_id, db_session)
    before_affected = affected_users_for_skill(before, db_session)

    replace_skill_grants(skill_id, body.group_ids, db_session=db_session)
    db_session.commit()

    updated = fetch_skill_for_admin(skill_id, db_session)
    after_affected = affected_users_for_skill(updated, db_session)
    _push_skills_to_sandboxes(before_affected | after_affected, db_session)

    return CustomSkillResponse.from_model(updated, group_ids=body.group_ids)
```

### `DELETE /admin/skills/custom/{id}`

```python
def delete_custom_skill(...) -> None:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected = affected_users_for_skill(skill, db_session)
    old_file_id = delete_skill(skill_id, db_session)
    db_session.commit()

    _push_skills_to_sandboxes(affected, db_session)
    if old_file_id is not None:
        _delete_old_bundle(get_default_file_store(), old_file_id)
```

### `GET /skills` (user)

```python
def list_skills_for_current_user(...) -> SkillsList:
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        BuiltinSkillResponse.from_skill(b, db_session)
        for b in registry.list_available(db_session)
    ]
    customs = list_skills_for_user(user=user, db_session=db_session)
    return SkillsList(
        builtins=builtins,
        # Users don't see grant details — group_ids always empty in user view
        customs=[CustomSkillResponse.from_model(c, group_ids=[]) for c in customs],
    )
```

### `GET /admin/skills`

Like the user list but uses `registry.list_all()` (not `list_available`) and computes `is_available` / `unavailable_reason` per-skill by calling `skill.is_available(db_session)`. Custom skills returned via `list_skills_for_admin` include disabled ones. Group grants fetched per-skill.

```python
def list_skills_admin(...) -> SkillsList:
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        BuiltinSkillResponse.from_skill(b, db_session)
        for b in registry.list_all()
    ]
    customs = list_skills_for_admin(db_session=db_session)
    return SkillsList(
        builtins=builtins,
        customs=[
            CustomSkillResponse.from_model(c, group_ids=_get_group_ids(c.id, db_session))
            for c in customs
        ],
    )
```

### Shared push helper

```python
def _push_skill_to_affected_sandboxes(skill: Skill, db_session: Session) -> None:
    affected = affected_users_for_skill(skill, db_session)
    _push_skills_to_sandboxes(affected, db_session)

def _push_skills_to_sandboxes(users: set[User], db_session: Session) -> None:
    if not users:
        return
    sandbox_map = get_sandbox_user_map([u.id for u in users], db_session)
    sandbox_files = {
        sid: build_skills_files_for_user(user, db_session)
        for sid, user in sandbox_map.items()
    }
    get_sandbox_manager().push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
```

## 7. Router Registration

In `backend/onyx/main.py`, alongside the existing imports + `include_router_with_global_prefix_prepended` calls:

```python
from onyx.server.features.skill.api import admin_router as admin_skill_router
from onyx.server.features.skill.api import user_router as skill_router

include_router_with_global_prefix_prepended(application, skill_router)
include_router_with_global_prefix_prepended(application, admin_skill_router)
```

## 8. Tests

The default test type for this work is **integration**, since the value is the wire-level contract. Add unit tests only where logic is sufficiently tricky.

### `SkillManager` (`backend/tests/integration/common_utils/managers/skill.py`)

Mirror the `PersonaManager` shape — static methods, real HTTP, returns `DATestSkill`:
- `create_custom(user_performing_action, *, slug=None, name=None, description=None, is_public=False, group_ids=None, bundle_bytes=None) -> DATestSkill`
- `patch_custom(skill, user_performing_action, **fields) -> DATestSkill`
- `replace_bundle(skill, bundle_bytes, user_performing_action) -> DATestSkill`
- `replace_grants(skill, group_ids, user_performing_action) -> None`
- `delete_custom(skill, user_performing_action) -> None`
- `list_all(user_performing_action) -> SkillsList`
- `list_for_user(user_performing_action) -> SkillsList`
- `verify(skill, user_performing_action) -> bool`

Add a small helper that builds a valid in-memory zip (with `SKILL.md` + frontmatter) for upload tests.

### `test_skills_admin.py`
Cover the admin happy paths plus the load-bearing error cases:
- create → list → patch (slug, name, description, is_public, enabled) → replace bundle → delete.
- duplicate slug → 4xx with `DUPLICATE_RESOURCE`.
- slug clashing with a registered built-in → 4xx with `INVALID_INPUT`.
- PATCH slug to a reserved built-in slug → 4xx with `INVALID_INPUT`.
- bundle missing `SKILL.md` → 4xx.
- bundle with a `.template` file → 4xx.
- bundle over size limit → 4xx.
- grants replace: empty list → no rows; non-empty list → exact rows present.
- grants replace with non-existent group ID → 4xx (FK violation).
- delete is idempotent (404 on second call is acceptable).

### `test_skills_user.py`
- Non-admin cannot hit admin endpoints (403).
- Public custom appears in `GET /skills` for every user.
- Private custom appears only for users in granted groups; absent for others.
- Disabled skill never appears in user list.
- Built-ins with `is_available=False` are absent from user list and present-with-reason in admin list.

### Unit tests
- `SkillPatchRequest.to_domain()` correctly maps `model_fields_set` to `UNSET` — verifies that omitted fields produce `UNSET`, explicitly-sent fields (including `None` for nullable fields) produce their value.

## 9. Suggested Subagent Decomposition

**Hard dependency**: this work depends on `SandboxManager` having `push_to_sandbox` / `push_to_sandboxes` methods landed (see sandbox-file-push.md workstream); can be stubbed for testing in the meantime.

Stage 1 (sequential — establishes the contract):
- **A. Models + skeleton router** — write `models.py`, `api.py` with route signatures returning `NotImplementedError`, and register them in `main.py`. Add `SkillPatch` dataclass to `db/skill.py`. Add `get_sandbox_user_map` to `backend/onyx/server/features/build/db/sandbox.py`. Output: typecheck-clean skeleton.

Stage 2 (parallel — independent feature slices, all consume Stage 1 output):
- **B. Admin write endpoints** — `POST/PATCH/PUT/DELETE` on `/admin/skills/custom*`. Owns the create / patch / replace-bundle / grants / delete code paths. Owns `backend/onyx/skills/push.py` (`build_skills_files_for_user`, `push_to_pod`) and `affected_users_for_skill` in `backend/onyx/db/skill.py`. Consumes the `SandboxManager` push API.
- **C. Read endpoints (admin + user)** — `GET /admin/skills` and `GET /skills`. Owns the built-in/custom merge logic and the `from_model` factories. Must not import from `push.py`.
- **D. Test scaffolding** — `SkillManager`, `DATestSkill`, the zip-builder helper, and the directory `backend/tests/integration/tests/skills/`. Stubs out one happy-path test per file to lock the manager API.

Stage 3 (parallel — depends on B/C/D being landed):
- **E. Admin test suite** — fills out `test_skills_admin.py` against the real B endpoints.
- **F. User test suite** — fills out `test_skills_user.py`.
- **G. Unit test for `SkillPatchRequest.to_domain()` sentinel mapping.**

## 10. Conventions Checklist

For any subagent touching this code:

- Raise `OnyxError(OnyxErrorCode.*)` — never `HTTPException`, never raw status codes. Use `INVALID_INPUT` (not `INVALID_REQUEST`, which doesn't exist) for validation errors.
- Do **not** use `response_model=` on endpoint decorators; rely on return-type annotations.
- DB ops live in `backend/onyx/db/skill.py` — endpoints must not run SQL directly.
- Commit transactions at the endpoint boundary; DB-layer functions only flush.
- `push_to_sandboxes` runs **after** `db_session.commit()`. Push failures are logged inside `SandboxManager` and recorded in the returned `PushResult` (from `backend/onyx/server/features/build/sandbox/models.py`) — they don't surface as request errors. The request returns success on partial pod-level failure (the next mutation or cold-start hydration re-converges). This latency is acceptable for V1; for large tenants with many active sandboxes, the synchronous fan-out could move to a background task in a future iteration.
- `validate_custom_bundle` already checks reserved slugs, size limits, and bundle format. Don't duplicate these checks in the endpoint — let the validator be the single source of truth. The PATCH endpoint additionally validates slug format via `check_slug()` and checks reserved slugs (the validator only runs on bundle uploads).
- Old bundle blobs are deleted inline via `_delete_old_bundle` (best-effort with warning log on failure) after commit + push. No periodic sweep needed.
- Strict typing — no `Any` unless unavoidable.
- Use existing fixtures (`admin_user`, `basic_user`, `reset`) for integration tests; don't construct users manually.
