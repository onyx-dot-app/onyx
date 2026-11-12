from collections.abc import Callable
from typing import Annotated, NamedTuple
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import Field, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import (
    has_global_permission,
    require_permission,
)
from onyx.db.engine.sql_engine import get_session, get_session_with_tenant
from onyx.db.enums import (
    AccountType,
    ExternalAppType,
    Permission,
)
from onyx.db.external_app import (
    get_built_in_external_app,
    get_external_app_by_id,
)
from onyx.db.models import Skill, User
from onyx.db.plugin import (
    AddedPluginVersion,
    get_organization_library_default,
    get_plugin_current_version_id,
    get_plugin_version,
    list_plugin_versions,
    lock_skill_plugin__no_commit,
    set_organization_library_default__no_commit,
)
from onyx.db.plugin_review import list_review_requests
from onyx.db.skill import (
    SkillManagementPolicy,
    SkillSharingChange,
    affected_user_ids_for_skill,
    approve_skill_review__no_commit,
    bulk_share_skills__no_commit,
    bulk_update_skill__no_commit,
    create_custom_skill__no_commit,
    create_skill_from_bundle__no_commit,
    delete_skill_for_user__no_commit,
    deny_skill_review__no_commit,
    enable_new_skill_if_name_available__no_commit,
    ensure_can_edit_org_visibility,
    fetch_skill,
    list_skills,
    publish_skill__no_commit,
    replace_skill_bundle,
    set_skill_enabled_for_user,
    share_skill__no_commit,
    transfer_skill_ownership,
)
from onyx.db.skill_limit import skill_limit_refusal, users_past_write_limit
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.skill.models import (
    GitHubImportedSkill,
    GitHubSkillNotImported,
    GitHubSkillPreview,
    GitHubSkillsImportRequest,
    GitHubSkillsImportResponse,
    GitHubSkillsPreviewRequest,
    GitHubSkillsPreviewResponse,
    OrganizationLibraryDefaultAccess,
    SkillBulkActionRequest,
    SkillBulkFailure,
    SkillBulkResponse,
    SkillBulkShareRequest,
    SkillBundleInspectResponse,
    SkillCreateRequest,
    SkillEditableDetailResponse,
    SkillEnableRequest,
    SkillLimitUser,
    SkillLimitUsersResponse,
    SkillPatchRequest,
    SkillPreviewResponse,
    SkillPublishRequest,
    SkillResponse,
    SkillReviewRequestResponse,
    SkillShareRequest,
    SkillsList,
    SkillVersionPreviewResponse,
    SkillVersionResponse,
    SkillVersionRestoreRequest,
    TransferSkillOwnershipRequest,
)
from onyx.server.features.skill.response_helpers import (
    skill_preview_response,
    skill_response_for_user,
    skills_list_response_for_user,
)
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    build_single_file_bundle,
    build_skill_md,
    check_skill_md_size,
    compute_bundle_manifest,
    inspect_custom_bundle,
    normalize_custom_bundle,
    open_bundle_zip,
    read_bundle_file,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    update_custom_bundle_files,
)
from onyx.skills.content import (
    read_version_bundle_bytes,
    read_version_contents,
    read_version_preview,
)
from onyx.skills.ingest import (
    IngestedBundle,
    delete_bundle_blob,
    ingest_skill_bundle,
    ingested_skill_bundle,
)
from onyx.skills.ingest_from_github import fetch_github_skill_bundles
from onyx.skills.limits import (
    SKILL_RUNTIME_MAX_BYTES,
    SKILL_RUNTIME_MAX_FILES,
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
)
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import GITHUB_SKILL_MAX_COUNT
from onyx.skills.push import push_skill_to_affected_sandboxes, push_skills_for_users
from shared_configs.contextvars import get_current_tenant_id

user_router = APIRouter(prefix="/skills")


def _parse_skill_sharing(sharing: str | None) -> SkillShareRequest | None:
    try:
        return SkillShareRequest.model_validate_json(sharing) if sharing else None
    except ValidationError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Invalid skill sharing settings."
        ) from exc


class _BundleSource(NamedTuple):
    path: str
    name: str
    ingest: Callable[[FileStore], IngestedBundle]


def _import_skill_bundles(
    sources: list[_BundleSource],
    not_imported: list[GitHubSkillNotImported],
    change: SkillSharingChange | None,
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> GitHubSkillsImportResponse:
    """Store each bundle and create its skill in its own savepoint, commit once,
    then push to the affected sandboxes. A rejected skill drops its blob and
    lands in not_imported; a failed commit drops every blob."""
    file_store = get_default_file_store()
    created: list[tuple[Skill, bool]] = []
    affected: set[UUID] = set()
    bundle_file_ids: list[str] = []
    try:
        for source in sources:
            try:
                ingested = source.ingest(file_store)
            except OnyxError as exc:
                not_imported.append(
                    GitHubSkillNotImported(
                        path=source.path, name=source.name, reason=exc.detail
                    )
                )
                continue
            bundle_file_ids.append(ingested.bundle_file_id)
            try:
                skill, enabled, item_affected = create_skill_from_bundle__no_commit(
                    ingested, change, auto_enable, user, db_session
                )
            except OnyxError as exc:
                delete_bundle_blob(file_store, bundle_file_ids.pop())
                not_imported.append(
                    GitHubSkillNotImported(
                        path=source.path,
                        name=source.name,
                        reason=exc.detail,
                        skill_limit=skill_limit_refusal(exc),
                    )
                )
                continue
            created.append((skill, enabled))
            affected |= item_affected
        db_session.commit()
    except Exception:
        # Nothing references the stored blobs once the import fails.
        for file_id in bundle_file_ids:
            delete_bundle_blob(file_store, file_id)
        raise
    if affected:
        push_skills_for_users(affected, db_session)
        db_session.commit()
    return _import_response(created, not_imported, auto_enable, user, db_session)


def _import_response(
    created: list[tuple[Skill, bool]],
    not_imported: list[GitHubSkillNotImported],
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> GitHubSkillsImportResponse:
    return GitHubSkillsImportResponse(
        imported=[
            GitHubImportedSkill(
                skill=skill_response_for_user(
                    skill, user, db_session, include_share_details=True
                ),
                disabled_reason=(
                    f"Another skill named “{skill.name}” is already enabled."
                    if auto_enable and not enabled
                    else None
                ),
            )
            for skill, enabled in created
        ],
        not_imported=not_imported,
    )


def _github_authorization_header(user: User) -> str | None:
    tenant_id = get_current_tenant_id()
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        github_app = get_built_in_external_app(db_session, ExternalAppType.GITHUB)
        if github_app is None or not github_app.enabled:
            return None
        github_app_id = github_app.id

    ensure_fresh_credentials(tenant_id, github_app_id, user.id)
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        return resolve_injection_headers(
            db_session,
            github_app_id,
            user.id,
        ).get("Authorization")


def _delete_bundle_blobs(file_store: FileStore, file_ids: list[str]) -> None:
    """Delete bundles after the commit that stopped using them. A failed
    delete only logs."""
    for file_id in file_ids:
        delete_bundle_blob(file_store, file_id)


def _current_version_id(skill: Skill, db_session: Session) -> UUID:
    version_id = get_plugin_current_version_id(skill.id, db_session)
    if version_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill has no plugin version.")
    return version_id


def _bundle_to_edit(skill: Skill, db_session: Session) -> bytes:
    """The bundle of the version an edit starts from. The caller holds the
    skill row lock, and every save takes it first, so the current version
    cannot move under the edit. A skill with no plugin gets one from its
    legacy row first, as the save does."""
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    return read_version_bundle_bytes(plugin.current_version_id, db_session)


def _editable_skill_response(
    skill: Skill,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    version_id = _current_version_id(skill, db_session)
    bundle_contents = read_version_contents(version_id, db_session)
    response = skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
        shown_version_id=version_id,
    )
    return SkillEditableDetailResponse(
        **response.model_dump(),
        instructions_markdown=bundle_contents.instructions_markdown,
        files=bundle_contents.files,
    )


def _replace_skill_bundle_from_editor(
    skill: Skill,
    bundle_bytes: bytes,
    base_version_id: UUID | None,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    """Save an editor file change as a new plugin version. A change that leaves
    the files as they are adds no version."""
    file_store = get_default_file_store()
    with ingested_skill_bundle(
        bundle_bytes,
        f"{skill.name}.zip",
        file_store,
        expected_name=skill.name,
        # update_custom_bundle_files applied the limits that fit each edit.
        upload_limits=False,
    ) as ingested:
        added = replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            base_version_id=base_version_id,
            user=user,
            skip_if_unchanged=True,
            previous_manifest=lambda: compute_bundle_manifest(
                _bundle_to_edit(skill, db_session)
            ),
            db_session=db_session,
        )
        db_session.commit()

    if added is None:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        return _editable_skill_response(skill, user, db_session)
    _delete_bundle_blobs(file_store, added.pruned_bundle_file_ids)
    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    db_session.commit()
    return _editable_skill_response(skill, user, db_session)


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list_skills(
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    return skills_list_response_for_user(rows, user, db_session)


@user_router.post("/bulk")
def bulk_update_skills(
    request: Annotated[
        SkillBulkShareRequest | SkillBulkActionRequest,
        Field(discriminator="action"),
    ],
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillBulkResponse:
    succeeded: list[UUID] = []
    failed: list[SkillBulkFailure] = []
    affected: set[UUID] = set()
    deleted_file_ids: list[str] = []
    if isinstance(request, SkillBulkShareRequest):
        shared = bulk_share_skills__no_commit(
            request.skill_ids, request.sharing.to_change(), user, db_session
        )
        succeeded = shared.succeeded
        failed = [
            SkillBulkFailure(
                skill_id=skill_id,
                detail=exc.detail,
                skill_limit=skill_limit_refusal(exc),
            )
            for skill_id, exc in shared.failed
        ]
        affected = shared.affected_user_ids
    else:
        for skill_id in sorted(set(request.skill_ids)):
            try:
                item_affected, item_file_ids = bulk_update_skill__no_commit(
                    skill_id, request.action, user, db_session
                )
            except OnyxError as exc:
                failed.append(
                    SkillBulkFailure(
                        skill_id=skill_id,
                        detail=exc.detail,
                        skill_limit=skill_limit_refusal(exc),
                    )
                )
                continue
            succeeded.append(skill_id)
            affected |= item_affected
            deleted_file_ids.extend(item_file_ids)
    db_session.commit()
    push_skills_for_users(affected, db_session)
    db_session.commit()
    if deleted_file_ids:
        _delete_bundle_blobs(get_default_file_store(), deleted_file_ids)
    return SkillBulkResponse(succeeded=succeeded, failed=failed)


@user_router.put("/{skill_id}/enabled")
def set_skill_enabled_for_current_user(
    skill_id: UUID,
    request: SkillEnableRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = set_skill_enabled_for_user(
        skill_id=skill_id,
        enabled=request.enabled,
        replace_conflict=request.replace_conflict,
        user=user,
        db_session=db_session,
    )
    db_session.commit()
    push_skills_for_users({user.id}, db_session)
    db_session.commit()
    return skill_response_for_user(skill, user, db_session)


@user_router.get("/review-requests")
def list_skill_review_requests(
    _: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> list[SkillReviewRequestResponse]:
    return [
        SkillReviewRequestResponse(
            skill_id=request.plugin_id,
            name=request.name,
            version_id=request.version_id,
            version_number=request.version_number,
            published_version_number=request.published_version_number,
            requested_by_email=request.requested_by_email,
            requested_at=request.requested_at,
        )
        for request in list_review_requests(db_session)
    ]


@user_router.get("/organization-library/default-access")
def get_organization_library_default_access(
    _: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> OrganizationLibraryDefaultAccess:
    return OrganizationLibraryDefaultAccess(
        installation_policy=get_organization_library_default(db_session)
    )


@user_router.put("/organization-library/default-access")
def set_organization_library_default_access(
    request: OrganizationLibraryDefaultAccess,
    _: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> OrganizationLibraryDefaultAccess:
    affected = set_organization_library_default__no_commit(
        request.installation_policy, db_session
    )
    db_session.commit()
    push_skills_for_users(affected, db_session)
    db_session.commit()
    return OrganizationLibraryDefaultAccess(
        installation_policy=request.installation_policy
    )


@user_router.get("/users-over-limit")
def list_users_over_skill_limit(
    _: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> SkillLimitUsersResponse:
    """Active users past 500 MB or 5,000 files of skills, with how many of
    their skills the run-time limit leaves out."""
    return SkillLimitUsersResponse(
        max_bytes=SKILL_WRITE_MAX_BYTES,
        max_files=SKILL_WRITE_MAX_FILES,
        runtime_max_bytes=SKILL_RUNTIME_MAX_BYTES,
        runtime_max_files=SKILL_RUNTIME_MAX_FILES,
        users=[
            SkillLimitUser(
                user_id=user.user_id,
                email=user.email,
                bytes=user.usage.bytes,
                files=user.usage.files,
                skills_not_loaded=user.skills_not_loaded,
            )
            for user in users_past_write_limit(db_session)
        ],
    )


@user_router.get("/{skill_id}")
def fetch_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_response_for_user(skill, user, db_session)


@user_router.get("/{skill_id}/preview")
def preview_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillPreviewResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_preview_response(skill, user, db_session)


@user_router.post("/custom")
def create_custom_skill(
    bundle: UploadFile = File(...),
    auto_enable: Annotated[bool, Form()] = True,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file, filename=bundle.filename),
        bundle.filename,
        file_store,
    ) as ingested:
        skill, _ = create_custom_skill__no_commit(ingested, user, db_session)
        if auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{skill.name}' is already enabled.",
            )
        db_session.commit()

    if auto_enable:
        push_skill_to_affected_sandboxes(skill, db_session)
        db_session.commit()

    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.post("/custom/batch")
def create_custom_skills_batch(
    bundles: Annotated[list[UploadFile], File()],
    auto_enable: Annotated[bool, Form()] = True,
    sharing: Annotated[str | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> GitHubSkillsImportResponse:
    if not 1 <= len(bundles) <= GITHUB_SKILL_MAX_COUNT:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Upload between 1 and {GITHUB_SKILL_MAX_COUNT} skill bundles.",
        )
    share_request = _parse_skill_sharing(sharing)
    sources = [
        _BundleSource(
            path=bundle.filename or SKILL_MD_NAME,
            name=bundle.filename or SKILL_MD_NAME,
            ingest=lambda file_store, bundle=bundle: ingest_skill_bundle(
                read_bundle_file(bundle.file, filename=bundle.filename),
                bundle.filename,
                file_store,
            ),
        )
        for bundle in bundles
    ]
    return _import_skill_bundles(
        sources,
        [],
        share_request.to_change() if share_request is not None else None,
        auto_enable,
        user,
        db_session,
    )


@user_router.post("/github/preview")
def preview_github_skills(
    request: GitHubSkillsPreviewRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> GitHubSkillsPreviewResponse:
    repository, skills = fetch_github_skill_bundles(
        request.repository,
        _github_authorization_header(user),
    )
    return GitHubSkillsPreviewResponse(
        repository=f"{repository.owner}/{repository.repo}",
        revision=repository.revision,
        subpath=repository.subpath,
        skills=[
            GitHubSkillPreview(
                path=skill.path,
                name=skill.name,
                description=skill.description,
                unavailable_reason=skill.unavailable_reason,
            )
            for skill in skills
        ],
    )


@user_router.post("/github/import")
def import_github_skills(
    request: GitHubSkillsImportRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> GitHubSkillsImportResponse:
    _, discovered_skills = fetch_github_skill_bundles(
        request.repository,
        _github_authorization_header(user),
        revision=request.revision,
        subpath=request.subpath,
        selected_paths=set(request.paths),
    )
    skills_by_path = {skill.path: skill for skill in discovered_skills}
    not_imported: list[GitHubSkillNotImported] = []
    sources: list[_BundleSource] = []
    for path in dict.fromkeys(request.paths):
        selected_skill = skills_by_path.get(path)
        if selected_skill is None:
            not_imported.append(
                GitHubSkillNotImported(
                    path=path,
                    name=path.rsplit("/", maxsplit=1)[-1],
                    reason="This skill was not found in the previewed revision.",
                )
            )
            continue
        if (
            selected_skill.bundle_bytes is None
            or selected_skill.unavailable_reason is not None
        ):
            not_imported.append(
                GitHubSkillNotImported(
                    path=path,
                    name=selected_skill.name,
                    reason=selected_skill.unavailable_reason
                    or "This skill cannot be imported.",
                )
            )
            continue
        sources.append(
            _BundleSource(
                path=path,
                name=selected_skill.name,
                ingest=lambda file_store, skill=selected_skill: ingest_skill_bundle(
                    skill.bundle_bytes or b"",
                    f"{skill.name}.zip",
                    file_store,
                    expected_name=skill.name,
                ),
            )
        )
    return _import_skill_bundles(
        sources,
        not_imported,
        request.sharing.to_change() if request.sharing is not None else None,
        True,
        user,
        db_session,
    )


@user_router.post("/custom/editor")
def create_custom_skill_from_editor(
    name: Annotated[str, Form(min_length=1)],
    description: Annotated[str, Form(min_length=1)],
    instructions_markdown: Annotated[str, Form(min_length=1)],
    upload: Annotated[UploadFile | None, File()] = None,
    auto_enable: Annotated[bool, Form()] = True,
    external_app_id: Annotated[int | None, Form(gt=0)] = None,
    sharing: Annotated[str | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    if external_app_id is not None:
        if not has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Only administrators can create a skill for an external app.",
            )
        if get_external_app_by_id(db_session, external_app_id) is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "External app not found.")

    share_request = _parse_skill_sharing(sharing)

    try:
        create_request = SkillCreateRequest(
            name=name,
            description=description,
            instructions_markdown=instructions_markdown,
        )
    except ValidationError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Skill name, description, and instructions cannot be empty.",
        ) from exc
    bundle_bytes = build_single_file_bundle(
        SKILL_MD_NAME,
        build_skill_md(
            name=create_request.name,
            description=create_request.description,
            instructions_markdown=create_request.instructions_markdown,
        ).encode("utf-8"),
    )
    canonical_name = create_request.name
    if upload is not None:
        bundle_bytes = update_custom_bundle_files(
            bundle_bytes,
            read_bundle_file(upload.file, filename=upload.filename),
            filename=upload.filename,
        )
    bundle_bytes = rewrite_custom_bundle_skill_md(
        bundle_bytes,
        canonical_name=canonical_name,
        description=create_request.description,
        instructions_markdown=create_request.instructions_markdown,
    )
    file_store = get_default_file_store()
    should_auto_enable = auto_enable and external_app_id is None
    with ingested_skill_bundle(
        bundle_bytes,
        f"{canonical_name}.zip",
        file_store,
        expected_name=canonical_name,
    ) as ingested:
        skill, _ = create_custom_skill__no_commit(
            ingested,
            user,
            db_session,
            change=share_request.to_change() if share_request is not None else None,
            external_app_id=external_app_id,
        )
        if should_auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{skill.name}' is already enabled.",
            )
        db_session.commit()

    if should_auto_enable or share_request is not None:
        push_skill_to_affected_sandboxes(skill, db_session)
        db_session.commit()

    return _editable_skill_response(skill, user, db_session)


@user_router.get("/custom/{skill_id}/edit")
def fetch_custom_skill_for_edit(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    return _editable_skill_response(skill, user, db_session)


@user_router.post("/custom/bundle/inspect")
def inspect_custom_skill_bundle_upload(
    upload: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
) -> SkillBundleInspectResponse:
    if not upload.filename:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "upload is missing a filename")

    upload_bytes = read_bundle_file(upload.file, filename=upload.filename)
    if upload.filename.lower() == SKILL_MD_NAME.lower():
        upload_bytes = build_single_file_bundle(SKILL_MD_NAME, upload_bytes)
    elif not upload.filename.lower().endswith(".zip"):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "upload must be SKILL.md or a ZIP containing SKILL.md",
        )

    normalized = normalize_custom_bundle(upload_bytes)
    with open_bundle_zip(normalized.content) as bundle_zip:
        raw_skill_md = bundle_zip.read(SKILL_MD_NAME)
    check_skill_md_size(raw_skill_md)
    document = parse_skill_document(
        raw_skill_md,
        directory_name=normalized.source_directory,
    )
    contents = inspect_custom_bundle(normalized.content)
    return SkillBundleInspectResponse(
        name=document.metadata.name,
        description=document.metadata.description,
        instructions_markdown=contents.instructions_markdown,
        files=contents.files,
    )


@user_router.get("/custom/{skill_id}/versions")
def list_custom_skill_versions(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[SkillVersionResponse]:
    """Every version, newest first."""
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return [
        SkillVersionResponse(
            id=version.id,
            version_number=version.version_number,
            created_at=version.created_at,
            created_by_email=version.created_by_email,
            bundle_kept=version.bundle_file_id is not None,
            is_current=is_current,
            review_status="published" if is_published else version.review_status.value,
        )
        for version, is_current, is_published in list_plugin_versions(
            skill.id, db_session
        )
    ]


@user_router.get("/custom/{skill_id}/versions/{version_id}")
def preview_custom_skill_version(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillVersionPreviewResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    version = get_plugin_version(skill.id, version_id, db_session)
    stored, contents = read_version_preview(version_id, db_session)
    return SkillVersionPreviewResponse(
        version_number=version.version_number,
        description=stored.description or "",
        instructions_markdown=contents.instructions_markdown,
    )


@user_router.post("/custom/{skill_id}/versions/{version_id}/restore")
def restore_custom_skill_version(
    skill_id: UUID,
    version_id: UUID,
    request: SkillVersionRestoreRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    """Copy an old version's files into a new version. Content equal to the
    current version adds no version."""
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    get_plugin_version(skill.id, version_id, db_session)
    return _replace_skill_bundle_from_editor(
        skill,
        read_version_bundle_bytes(version_id, db_session),
        request.base_version_id,
        user,
        db_session,
    )


@user_router.post("/custom/{skill_id}/publish")
def publish_current_user_skill(
    skill_id: UUID,
    request: SkillPublishRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    """Publish the current version: to the organization for a private skill,
    as a publish update for a published one. The Publishing setting can make
    this a review request or refuse it."""
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    affected = publish_skill__no_commit(
        skill, request.base_version_id, user, db_session
    )
    db_session.commit()
    db_session.expire(skill)
    if affected:
        push_skills_for_users(affected, db_session)
        db_session.commit()
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


def _skill_to_review(skill_id: UUID, user: User, db_session: Session) -> Skill:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill


@user_router.post("/custom/{skill_id}/versions/{version_id}/approve")
def approve_skill_review(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = _skill_to_review(skill_id, user, db_session)
    affected = approve_skill_review__no_commit(skill, version_id, db_session)
    db_session.commit()
    db_session.expire(skill)
    push_skills_for_users(affected, db_session)
    db_session.commit()
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


@user_router.post("/custom/{skill_id}/versions/{version_id}/deny")
def deny_skill_review(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = _skill_to_review(skill_id, user, db_session)
    deny_skill_review__no_commit(skill, version_id, db_session)
    db_session.commit()
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


@user_router.put("/custom/{skill_id}/bundle")
def replace_current_user_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    base_version_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file, filename=bundle.filename),
        bundle.filename,
        file_store,
        expected_name=skill.name,
    ) as ingested:
        # An upload always adds a version, also for the same zip.
        added = replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            base_version_id=base_version_id,
            user=user,
            skip_if_unchanged=False,
            db_session=db_session,
        )
        db_session.commit()

    if added is not None:
        _delete_bundle_blobs(file_store, added.pruned_bundle_file_ids)
    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    db_session.commit()
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.post("/custom/{skill_id}/files")
def upload_current_user_skill_files(
    skill_id: UUID,
    upload: UploadFile = File(...),
    base_version_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    updated_bundle_bytes = update_custom_bundle_files(
        lambda: _bundle_to_edit(skill, db_session),
        read_bundle_file(upload.file, filename=upload.filename),
        filename=upload.filename,
    )
    return _replace_skill_bundle_from_editor(
        skill, updated_bundle_bytes, base_version_id, user, db_session
    )


@user_router.delete("/custom/{skill_id}/files")
def remove_current_user_skill_file(
    skill_id: UUID,
    path: str,
    base_version_id: Annotated[UUID | None, Query()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if not path:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Skill file path cannot be empty")

    updated_bundle_bytes = update_custom_bundle_files(
        _bundle_to_edit(skill, db_session),
        remove_path=path,
    )
    return _replace_skill_bundle_from_editor(
        skill, updated_bundle_bytes, base_version_id, user, db_session
    )


@user_router.patch("/custom/{skill_id}")
def patch_current_user_skill(
    skill_id: UUID,
    patch_req: SkillPatchRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if "public_permission" in patch_req.model_fields_set:
        ensure_can_edit_org_visibility(skill, user)
    if not (patch_req.has_details_update or patch_req.has_db_field_update):
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    old_public_permission = skill.public_permission
    before_affected = affected_user_ids_for_skill(skill, db_session)
    file_store = get_default_file_store() if patch_req.has_details_update else None
    new_bundle_file_id: str | None = None
    added: AddedPluginVersion | None = None

    try:
        if file_store is not None:
            old_bundle_bytes = _bundle_to_edit(skill, db_session)
            description = (
                patch_req.description
                if patch_req.description is not None
                else skill.description
            )
            instructions_markdown = patch_req.instructions_markdown
            if instructions_markdown is None:
                instructions_markdown = read_custom_bundle_instructions(
                    old_bundle_bytes
                )
            new_bundle_bytes = rewrite_custom_bundle_skill_md(
                old_bundle_bytes,
                canonical_name=skill.name,
                description=description,
                instructions_markdown=instructions_markdown,
            )
            ingested = ingest_skill_bundle(
                new_bundle_bytes,
                f"{skill.name}.zip",
                file_store,
                expected_name=skill.name,
                upload_limits=False,
            )
            new_bundle_file_id = ingested.bundle_file_id
            added = replace_skill_bundle(
                skill=skill,
                ingested=ingested,
                base_version_id=patch_req.base_version_id,
                user=user,
                skip_if_unchanged=True,
                previous_manifest=lambda: compute_bundle_manifest(old_bundle_bytes),
                db_session=db_session,
            )

        if patch_req.has_db_field_update:
            share_skill__no_commit(
                skill,
                SkillSharingChange(
                    public_permission=patch_req.public_permission,
                    set_public_permission=True,
                ),
                user,
                db_session,
            )

        db_session.commit()
    except Exception:
        if file_store is not None and new_bundle_file_id is not None:
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    files_changed = added is not None
    if file_store is not None and new_bundle_file_id is not None and not files_changed:
        # Nothing references the bundle of an unchanged save.
        delete_bundle_blob(file_store, new_bundle_file_id)
    if file_store is not None and added is not None:
        _delete_bundle_blobs(file_store, added.pruned_bundle_file_ids)

    db_session.expire(skill)
    visibility_changed = old_public_permission != skill.public_permission
    if files_changed or visibility_changed:
        after_affected = affected_user_ids_for_skill(skill, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)
        db_session.commit()

    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.get("/custom/{skill_id}/share")
def fetch_custom_skill_sharing(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


@user_router.patch("/custom/{skill_id}/share")
def share_current_user_skill(
    skill_id: UUID,
    share_req: SkillShareRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if (
        share_req.user_shares is None
        and share_req.group_shares is None
        and share_req.group_settings is None
        and "installation_policy" not in share_req.model_fields_set
        and "public_permission" not in share_req.model_fields_set
    ):
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    affected = share_skill__no_commit(skill, share_req.to_change(), user, db_session)
    db_session.commit()
    db_session.expire(skill)
    push_skills_for_users(affected, db_session)
    db_session.commit()
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.post("/custom/{skill_id}/transfer-ownership")
def transfer_current_user_skill_ownership(
    skill_id: UUID,
    transfer_req: TransferSkillOwnershipRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and cannot change ownership.",
        )

    ownership_vacant = (
        skill.author_user_id is None
        or skill.author is None
        or not skill.author.is_active
    )
    if skill.author_user_id != user.id and not (
        has_global_permission(user, Permission.MANAGE_PLUGINS) and ownership_vacant
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only the owner can transfer ownership of this skill.",
        )

    target = fetch_user_by_id(db_session, transfer_req.new_owner_user_id)
    if target is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "New owner not found.")
    if not target.is_active:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership can only be transferred to an active user.",
        )
    if target.account_type is not None and target.account_type != AccountType.STANDARD:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership cannot be transferred to bots or service accounts.",
        )
    if target.id == skill.author_user_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This user already owns the skill.",
        )

    before_affected = affected_user_ids_for_skill(skill, db_session)
    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=target.id,
        db_session=db_session,
    )

    after_affected = affected_user_ids_for_skill(skill, db_session)
    db_session.commit()
    db_session.expire(skill)
    push_skills_for_users(before_affected | after_affected, db_session)
    db_session.commit()
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.delete("/custom/{skill_id}")
def delete_current_user_skill(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected, file_ids = delete_skill_for_user__no_commit(skill, user, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    db_session.commit()
    _delete_bundle_blobs(get_default_file_store(), file_ids)
