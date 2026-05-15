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
- Orphan-blob sweep job.
- Front-end work.

## 3. File Layout

New files (all under `backend/onyx/server/features/skill/`):

```
backend/onyx/server/features/skill/
├── __init__.py
├── api.py                   # routers, endpoints
└── models.py                # Pydantic request/response models
```

Plus the skills-side push helpers, co-located with the skills module:

```
backend/onyx/skills/push.py  # build_skills_files_for_user(user, db),
                             # push_to_pod(sandbox_id, user, db)
```

`build_skills_files_for_user` returns the flat path-to-bytes dict used as values in the `sandbox_files` mapping passed to `SandboxManager.push_to_sandboxes`; `push_to_pod` is the cold-start single-pod helper called from `setup_session_workspace`, internally calling `get_sandbox_manager().push_to_sandbox(...)` (see sandbox-file-push.md §11 and §12). Depends on `SandboxManager` gaining the push methods, but `backend/onyx/skills/push.py` itself does not change shape.

Modified files:
- `backend/onyx/main.py` — register the two routers.

New test files:
- `backend/tests/integration/common_utils/managers/skill.py` — `SkillManager`.
- `backend/tests/integration/common_utils/test_models.py` — `DATestSkill`.
- `backend/tests/integration/tests/skills/test_skills_admin.py`
- `backend/tests/integration/tests/skills/test_skills_user.py`

## 4. Pydantic Models (`models.py`)

Keep them flat and explicit. No `response_model=` on endpoint decorators (per CLAUDE.md); use return-type annotations only.

```python
class SkillSource(str, Enum):
    BUILTIN = "builtin"
    CUSTOM = "custom"

class BuiltinSkillSnapshot(BaseModel):
    source: Literal[SkillSource.BUILTIN] = SkillSource.BUILTIN
    slug: str
    name: str
    description: str
    is_available: bool
    unavailable_reason: str | None

class CustomSkillSnapshot(BaseModel):
    source: Literal[SkillSource.CUSTOM] = SkillSource.CUSTOM
    id: UUID
    slug: str
    name: str
    description: str
    is_public: bool
    enabled: bool
    bundle_sha256: str
    author_user_id: UUID | None
    granted_group_ids: list[int]   # admin view; empty for user view
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, skill: Skill, *, include_grants: bool) -> "CustomSkillSnapshot": ...

class SkillsAdminList(BaseModel):
    builtins: list[BuiltinSkillSnapshot]
    customs: list[CustomSkillSnapshot]

class SkillsUserList(BaseModel):
    builtins: list[BuiltinSkillSnapshot]
    customs: list[CustomSkillSnapshot]   # grants omitted for user view

class CustomSkillCreateForm:
    """Multipart form — defined as `Form()` params in the endpoint, not a BaseModel."""
    # slug: str, name: str, description: str, is_public: bool = False,
    # group_ids: list[int] = [], bundle: UploadFile

class CustomSkillPatch(BaseModel):
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    enabled: bool | None = None

class GrantsReplace(BaseModel):
    group_ids: list[int]
```

Notes:
- `CustomSkillPatch` uses `None` for "not provided" to match FastAPI ergonomics, but the endpoint must translate `None` → `UNSET` before calling `patch_skill` (which uses the existing sentinel).
- Listing is non-paginated in V1 (skill counts will be tiny). If/when needed, add `PaginatedReturn[CustomSkillSnapshot]` per the persona pattern.

## 5. Routes (`api.py`)

```python
admin_router = APIRouter(prefix="/admin/skills", tags=["skills"])
user_router = APIRouter(prefix="/skills", tags=["skills"])
```

### Admin endpoints

```python
@admin_router.get("")
def list_skills_admin(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillsAdminList: ...

@admin_router.post("/custom")
def create_custom_skill(
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    is_public: bool = Form(False),
    group_ids: list[int] = Form(default_factory=list),
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillSnapshot: ...

@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    patch: CustomSkillPatch,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillSnapshot: ...

@admin_router.put("/custom/{skill_id}/bundle")
def replace_custom_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillSnapshot: ...

@admin_router.put("/custom/{skill_id}/grants")
def replace_custom_skill_grants(
    skill_id: UUID,
    body: GrantsReplace,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillSnapshot: ...

@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None: ...
```

### User endpoints

```python
@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsUserList: ...
```

A single-skill GET is **optional** in V1 — only add if a concrete UI need exists.

## 6. Endpoint Implementation Sketches

Every mutation follows the same shape: validate → write to DB + FileStore → commit → compute the set of affected users → query DB for their sandbox_ids → build the sandbox_id-to-files mapping → push via `get_sandbox_manager().push_to_sandboxes(...)` (imported from `onyx.server.features.build.sandbox.base`). "Push" is a snapshot of the user's `mount_path`, so removing a skill = pushing the user's new file dict without that skill. There is no separate "unpush" call.

`affected_users_for_skill(skill, db_session)` (helper in `backend/onyx/skills/push.py`) returns the set of users with an active sandbox who should have this skill in their bundle — the uploader, plus all tenant users if `is_public`, plus members of granted groups. For visibility/grant transitions, the caller takes the union of the before-and-after sets so users who lost access also get re-pushed (without the skill).

### `POST /admin/skills/custom`

```python
def create_custom_skill(...) -> CustomSkillSnapshot:
    bundle_bytes = bundle.file.read()
    if len(bundle_bytes) > MAX_BUNDLE_BYTES:
        raise OnyxError(OnyxErrorCode.INVALID_REQUEST, "Bundle exceeds size limit")

    validate_custom_bundle(bundle_bytes, slug=slug)        # raises OnyxError on failure
    sha = compute_bundle_sha256(bundle_bytes)

    if slug in BuiltinSkillRegistry.instance().reserved_slugs():
        raise OnyxError(OnyxErrorCode.INVALID_REQUEST, "Slug reserved by a built-in skill")

    bundle_file_id = filestore.write(bundle_bytes)         # for persistence + cold start

    skill = create_skill(
        slug=slug, name=name, description=description,
        bundle_file_id=bundle_file_id, bundle_sha256=sha,
        is_public=is_public, author_user_id=user.id,
        db_session=db_session,
    )
    if group_ids:
        replace_skill_grants(skill.id, group_ids, db_session=db_session)
    db_session.commit()

    affected = affected_users_for_skill(skill, db_session)
    sandbox_ids = get_active_sandbox_ids_for_users([u.id for u in affected], db_session)
    sandbox_files = {sid: build_skills_files_for_user(u, db_session) for sid, u in sandbox_ids.items()}
    get_sandbox_manager().push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
    return CustomSkillSnapshot.from_model(<refetch with grants>, include_grants=True)
```

### `PATCH /admin/skills/custom/{id}`

```python
def patch_custom_skill(...) -> CustomSkillSnapshot:
    before = fetch_skill_for_admin(skill_id, db_session)
    before_affected = affected_users_for_skill(before, db_session)

    updated = patch_skill(skill_id, <translated patch>, db_session=db_session)
    db_session.commit()

    if visibility_or_enabled_changed(before, updated):
        after_affected = affected_users_for_skill(updated, db_session)
        users = before_affected | after_affected
        sandbox_ids = get_active_sandbox_ids_for_users([u.id for u in users], db_session)
        sandbox_files = {sid: build_skills_files_for_user(u, db_session) for sid, u in sandbox_ids.items()}
        get_sandbox_manager().push_to_sandboxes(
            mount_path="/workspace/managed/skills",
            sandbox_files=sandbox_files,
        )
    return CustomSkillSnapshot.from_model(updated, include_grants=True)
```

### `PUT /admin/skills/custom/{id}/bundle`

```python
def replace_custom_skill_bundle(...) -> CustomSkillSnapshot:
    bundle_bytes = bundle.file.read()
    validate_custom_bundle(bundle_bytes, slug=<existing slug>)
    sha = compute_bundle_sha256(bundle_bytes)
    new_file_id = filestore.write(bundle_bytes)

    updated, _old_file_id = replace_skill_bundle(
        skill_id=skill_id, new_bundle_file_id=new_file_id,
        new_bundle_sha256=sha, db_session=db_session,
    )
    db_session.commit()

    affected = affected_users_for_skill(updated, db_session)
    sandbox_ids = get_active_sandbox_ids_for_users([u.id for u in affected], db_session)
    sandbox_files = {sid: build_skills_files_for_user(u, db_session) for sid, u in sandbox_ids.items()}
    get_sandbox_manager().push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
    return CustomSkillSnapshot.from_model(updated, include_grants=True)
```

### `PUT /admin/skills/custom/{id}/grants`

```python
def replace_custom_skill_grants(...) -> CustomSkillSnapshot:
    before = fetch_skill_for_admin(skill_id, db_session)
    before_affected = affected_users_for_skill(before, db_session)

    replace_skill_grants(skill_id, body.group_ids, db_session=db_session)
    db_session.commit()

    updated = fetch_skill_for_admin(skill_id, db_session)
    after_affected = affected_users_for_skill(updated, db_session)
    users = before_affected | after_affected   # gainers get the skill, losers get it removed
    sandbox_ids = get_active_sandbox_ids_for_users([u.id for u in users], db_session)
    sandbox_files = {sid: build_skills_files_for_user(u, db_session) for sid, u in sandbox_ids.items()}
    get_sandbox_manager().push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
    return CustomSkillSnapshot.from_model(updated, include_grants=True)
```

### `DELETE /admin/skills/custom/{id}`

```python
def delete_custom_skill(...) -> None:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected = affected_users_for_skill(skill, db_session)
    delete_skill(skill_id, db_session)
    db_session.commit()

    # Push each previously-affected user their new (skill-free) file dict.
    sandbox_ids = get_active_sandbox_ids_for_users([u.id for u in affected], db_session)
    sandbox_files = {sid: build_skills_files_for_user(u, db_session) for sid, u in sandbox_ids.items()}
    get_sandbox_manager().push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
```

### `GET /skills` (user)

```python
def list_skills_for_current_user(...) -> SkillsUserList:
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        BuiltinSkillSnapshot(slug=b.slug, name=b.name, description=b.description,
                             is_available=True, unavailable_reason=None)
        for b in registry.list_available(db_session)
    ]
    customs = list_skills_for_user(user=user, db_session=db_session)
    return SkillsUserList(
        builtins=builtins,
        customs=[CustomSkillSnapshot.from_model(c, include_grants=False) for c in customs],
    )
```

### `GET /admin/skills`

Like the user list but returns **all** built-ins (with availability metadata) and **all** custom rows including disabled ones (via `list_skills_for_admin`) with grants populated.

## 7. Router Registration

In `backend/onyx/main.py`, alongside the existing imports + `include_router_with_global_prefix_prepended` calls:

```python
from onyx.server.features.skill.api import admin_router as admin_skill_router
from onyx.server.features.skill.api import user_router as skill_router

include_router_with_global_prefix_prepended(application, skill_router)
include_router_with_global_prefix_prepended(application, admin_skill_router)
```

## 8. Tests

The default test type for this work is **integration**, since the value is the wire-level contract. Add unit tests only where logic is sufficiently tricky (e.g., the `CustomSkillPatch` → `UNSET` translation).

### `SkillManager` (`backend/tests/integration/common_utils/managers/skill.py`)

Mirror the `PersonaManager` shape — static methods, real HTTP, returns `DATestSkill`:
- `create_custom(user_performing_action, *, slug=None, name=None, description=None, is_public=False, group_ids=None, bundle_bytes=None) -> DATestSkill`
- `patch_custom(skill, user_performing_action, **fields) -> DATestSkill`
- `replace_bundle(skill, bundle_bytes, user_performing_action) -> DATestSkill`
- `replace_grants(skill, group_ids, user_performing_action) -> None`
- `delete_custom(skill, user_performing_action) -> None`
- `list_admin(user_performing_action) -> SkillsAdminList`
- `list_for_user(user_performing_action) -> SkillsUserList`
- `verify(skill, user_performing_action) -> bool`

Add a small helper that builds a valid in-memory zip (with `SKILL.md` + frontmatter) for upload tests.

### `test_skills_admin.py`
Cover the admin happy paths plus the load-bearing error cases:
- create → list → patch (slug, name, description, is_public, enabled) → replace bundle → delete.
- duplicate slug → 4xx with `DUPLICATE_RESOURCE`.
- slug clashing with a registered built-in → 4xx with `INVALID_REQUEST`.
- bundle missing `SKILL.md` → 4xx.
- bundle with a `.template` file → 4xx.
- bundle over size limit → 4xx.
- grants replace: empty list → no rows; non-empty list → exact rows present.
- delete is idempotent (404 on second call is acceptable).

### `test_skills_user.py`
- Non-admin cannot hit admin endpoints (403).
- Public custom appears in `GET /skills` for every user.
- Private custom appears only for users in granted groups; absent for others.
- Disabled skill never appears in user list.
- Built-ins with `is_available=False` are absent from user list and present-with-reason in admin list.

### Unit test (small)
`CustomSkillPatch` translation to the `UNSET` sentinel preserves the difference between "not provided" and "set to null" (where applicable).

## 9. Suggested Subagent Decomposition

**Hard dependency**: this work depends on `SandboxManager` having `push_to_sandbox` / `push_to_sandboxes` methods landed (see sandbox-file-push.md workstream); can be stubbed for testing in the meantime. Under test, swap in a `SandboxManager` subclass that records `push_to_sandboxes` calls and asserts on the recorded calls.

Stage 1 (sequential — establishes the contract):
- **A. Models + skeleton router** — write `models.py`, `api.py` with route signatures returning `NotImplementedError`, and register them in `main.py`. Output: typecheck-clean skeleton.

Stage 2 (parallel — independent feature slices, all consume Stage 1 output):
- **B. Admin write endpoints** — `POST/PATCH/PUT/DELETE` on `/admin/skills/custom*`. Owns the create / patch / replace-bundle / grants / delete code paths. Owns `backend/onyx/skills/push.py` (`build_skills_files_for_user`, `affected_users_for_skill`, `push_to_pod`). Consumes — does **not** build — the `SandboxManager` push API; that's a separate parallel workstream (see `sandbox-file-push.md`).
- **C. Read endpoints (admin + user)** — `GET /admin/skills` and `GET /skills`. Owns the built-in/custom merge logic and the `from_model` factories.
- **D. Test scaffolding** — `SkillManager`, `DATestSkill`, the zip-builder helper, and the directory `backend/tests/integration/tests/skills/`. Stubs out one happy-path test per file to lock the manager API.

Stage 3 (parallel — depends on B/C/D being landed):
- **E. Admin test suite** — fills out `test_skills_admin.py` against the real B endpoints.
- **F. User test suite** — fills out `test_skills_user.py`.
- **G. Unit test for patch sentinel translation.**

The Stage 1 skeleton is the synchronization point that lets Stages 2 and 3 run in parallel without merge churn. Each Stage-2 agent should be told which other files are off-limits to avoid stepping on each other.

## 10. Conventions Checklist

For any subagent touching this code:

- Raise `OnyxError(OnyxErrorCode.*)` — never `HTTPException`, never raw status codes.
- Do **not** use `response_model=` on endpoint decorators; rely on return-type annotations.
- DB ops live in `backend/onyx/db/skill.py` — endpoints must not run SQL directly.
- Commit transactions at the endpoint boundary; DB-layer functions only flush.
- `get_sandbox_manager().push_to_sandboxes(...)` runs **after** `db_session.commit()`. Push failures are logged inside `SandboxManager` and recorded in the returned `PushResult` (from `backend/onyx/server/features/build/sandbox/models.py`) — they don't surface as request errors, and the request still returns success on partial pod-level failure (the next mutation or cold-start hydration re-converges).
- Strict typing — no `Any` unless unavoidable; same on the TS side if any client work follows.
- Use existing fixtures (`admin_user`, `basic_user`, `reset`) for integration tests; don't construct users manually.
