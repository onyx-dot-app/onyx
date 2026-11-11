from collections.abc import Callable, Container, Iterator
from contextlib import contextmanager
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
    associate_custom_skill_with_external_app__no_commit,
    get_built_in_external_app,
    get_external_app_by_id,
)
from onyx.db.models import Skill, User
from onyx.db.resource_access import lock_resource_access_user, mutate_resource_access
from onyx.db.skill import (
    SkillAccessAdapter,
    SkillManagementPolicy,
    SkillSharingChange,
    affected_user_ids_for_skill,
    bulk_update_skill__no_commit,
    create_skill_from_bundle__no_commit,
    create_skill_from_ingested_bundle,
    delete_skill_for_user__no_commit,
    enable_new_skill_if_name_available__no_commit,
    ensure_can_edit_org_visibility,
    fetch_skill,
    list_skills,
    replace_skill_bundle,
    set_skill_enabled_for_user,
    share_skill__no_commit,
    skill_ownership_is_vacant,
    transfer_skill_ownership,
)
from onyx.db.skill_version import (
    SkillContentSnapshot,
    delete_unreferenced_skill_bundles,
    fetch_skill_version,
    list_skill_versions,
    skill_content_snapshot,
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.file_processing.zip_index import ZipIndex
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.skill.models import (
    GitHubImportedSkill,
    GitHubSkillNotImported,
    GitHubSkillPreview,
    GitHubSkillsImportRequest,
    GitHubSkillsImportResponse,
    GitHubSkillsPreviewRequest,
    GitHubSkillsPreviewResponse,
    SkillBulkActionRequest,
    SkillBulkFailure,
    SkillBulkResponse,
    SkillBulkShareRequest,
    SkillBundleInspectResponse,
    SkillCreateRequest,
    SkillEditableDetailResponse,
    SkillEnableRequest,
    SkillPatchRequest,
    SkillPreviewResponse,
    SkillResponse,
    SkillShareRequest,
    SkillsList,
    SkillVersionResponse,
    TransferSkillOwnershipRequest,
)
from onyx.server.features.skill.response_helpers import (
    skill_preview_response,
    skill_response_for_user,
    skills_list_response_for_user,
)
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.bundle import (
    EVERY_PATH,
    SKILL_MD_NAME,
    build_single_file_bundle,
    build_skill_md,
    inspect_custom_bundle,
    normalize_custom_bundle,
    read_bundle_file,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    update_custom_bundle_files,
)
from onyx.skills.content import (
    read_custom_skill_bundle_bytes,
    read_stored_version_bundle,
)
from onyx.skills.ingest import (
    IngestedBundle,
    delete_bundle_blob,
    ingest_skill_bundle,
)
from onyx.skills.ingest_from_github import fetch_github_skill_bundles
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
    """Stage bundles before access locks; create skills with per-item savepoints.

    Commit once, then clean rejected uploads and push. An uncertain commit leaves
    staged blobs for the orphan sweep rather than risking referenced content.
    """
    file_store = get_default_file_store()
    created: list[tuple[Skill, bool]] = []
    affected: set[UUID] = set()
    staged: list[tuple[_BundleSource, IngestedBundle]] = []
    rejected: list[str] = []
    commit_attempted = False
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
            staged.append((source, ingested))
        user = lock_resource_access_user(user.id, db_session)
        for source, ingested in staged:
            try:
                skill, enabled, item_affected = create_skill_from_bundle__no_commit(
                    ingested, change, auto_enable, user, db_session
                )
            except OnyxError as exc:
                rejected.append(ingested.bundle_file_id)
                not_imported.append(
                    GitHubSkillNotImported(
                        path=source.path, name=source.name, reason=exc.detail
                    )
                )
                continue
            created.append((skill, enabled))
            affected |= item_affected
        commit_attempted = True
        db_session.commit()
    except Exception:
        db_session.rollback()
        if not commit_attempted:
            for _, ingested in staged:
                delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise
    for file_id in rejected:
        delete_bundle_blob(file_store, file_id)
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


def _editable_skill_response(
    skill: Skill,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    bundle_bytes = read_custom_skill_bundle_bytes(skill)
    response = skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )
    bundle_contents = inspect_custom_bundle(bundle_bytes)
    return SkillEditableDetailResponse(
        **response.model_dump(),
        instructions_markdown=bundle_contents.instructions_markdown,
        files=bundle_contents.files,
    )


@contextmanager
def _commit_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    db_session: Session,
    *,
    expected_name: str | None = None,
    stored: bool = False,
    uncapped_paths: Container[str] | None = None,
) -> Iterator[IngestedBundle]:
    """Commit references before cleanup; uncertain commits leave blobs for the sweep."""
    ingested = ingest_skill_bundle(
        bundle_bytes,
        filename,
        file_store,
        expected_name=expected_name,
        stored=stored,
        uncapped_paths=uncapped_paths,
    )
    commit_attempted = False
    try:
        yield ingested
        commit_attempted = True
        db_session.commit()
    except Exception:
        db_session.rollback()
        if not commit_attempted:
            delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise


def _lock_skill_after_storage(
    skill_id: UUID,
    user: User,
    db_session: Session,
    expected_content: SkillContentSnapshot | None = None,
) -> tuple[Skill, User]:
    actor = lock_resource_access_user(user.id, db_session)
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.EDIT,
        user=actor,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if (
        expected_content is not None
        and skill_content_snapshot(skill) != expected_content
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Skill content changed. Retry this request."
        )
    return skill, actor


def _replace_skill_bundle_from_editor(
    skill: Skill,
    bundle_bytes: bytes,
    user: User,
    db_session: Session,
    *,
    stored: bool = False,
    expected_content: SkillContentSnapshot | None = None,
    restored_version: tuple[UUID, str | None] | None = None,
    edited: bool = False,
) -> SkillEditableDetailResponse:
    """``edited`` marks bundles from update_custom_bundle_files, which already
    applied the path caps to the paths the edit added."""
    file_store = get_default_file_store()
    with _commit_skill_bundle(
        bundle_bytes,
        f"{skill.name}.zip",
        file_store,
        db_session,
        expected_name=skill.name,
        stored=stored,
        uncapped_paths=EVERY_PATH if edited else None,
    ) as ingested:
        skill, user = _lock_skill_after_storage(
            skill.id, user, db_session, expected_content
        )
        if restored_version is not None:
            version = fetch_skill_version(
                skill, restored_version[0], db_session, refresh=True
            )
            if version.bundle_file_id != restored_version[1]:
                raise OnyxError(
                    OnyxErrorCode.CONFLICT, "Version files changed. Retry this request."
                )
        stale_file_ids = replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            creator_id=user.id,
            db_session=db_session,
        )

    delete_unreferenced_skill_bundles(stale_file_ids, db_session)
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
    user = lock_resource_access_user(user.id, db_session)
    succeeded: list[UUID] = []
    failed: list[SkillBulkFailure] = []
    affected: set[UUID] = set()
    deleted_file_ids: list[str] = []
    if isinstance(request, SkillBulkShareRequest):
        result = mutate_resource_access(
            request.skill_ids,
            request.sharing.to_change(),
            user,
            db_session,
            SkillAccessAdapter(),
            add_only=True,
            allow_partial=True,
        )
        succeeded = result.succeeded
        failed = [
            SkillBulkFailure(skill_id=key, detail=value)
            for key, value in result.failed.items()
        ]
        affected = result.affected
    else:
        for skill_id in sorted(set(request.skill_ids)):
            try:
                item_affected, item_file_ids = bulk_update_skill__no_commit(
                    skill_id, request.action, user, db_session
                )
            except OnyxError as exc:
                failed.append(SkillBulkFailure(skill_id=skill_id, detail=exc.detail))
                continue
            succeeded.append(skill_id)
            affected |= item_affected
            deleted_file_ids.extend(item_file_ids)
    db_session.commit()
    push_skills_for_users(affected, db_session)
    db_session.commit()
    delete_unreferenced_skill_bundles(deleted_file_ids, db_session)
    return SkillBulkResponse(succeeded=succeeded, failed=failed)


@user_router.put("/{skill_id}/enabled")
def set_skill_enabled_for_current_user(
    skill_id: UUID,
    request: SkillEnableRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    user = lock_resource_access_user(user.id, db_session)
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
    with _commit_skill_bundle(
        read_bundle_file(bundle.file, filename=bundle.filename),
        bundle.filename,
        file_store,
        db_session,
    ) as ingested:
        user = lock_resource_access_user(user.id, db_session)
        skill = create_skill_from_ingested_bundle(ingested, user.id, db_session)
        if auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{skill.name}' is already enabled.",
            )

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
    with _commit_skill_bundle(
        bundle_bytes,
        f"{canonical_name}.zip",
        file_store,
        db_session,
        expected_name=canonical_name,
    ) as ingested:
        user = lock_resource_access_user(user.id, db_session)
        if external_app_id is not None and not has_global_permission(
            user, Permission.FULL_ADMIN_PANEL_ACCESS
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Only administrators can create a skill for an external app.",
            )
        skill = create_skill_from_ingested_bundle(ingested, user.id, db_session)
        if external_app_id is not None:
            associate_custom_skill_with_external_app__no_commit(
                db_session,
                external_app_id=external_app_id,
                skill_id=skill.id,
            )
        if share_request is not None:
            share_skill__no_commit(skill, share_request.to_change(), user, db_session)
        if should_auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{skill.name}' is already enabled.",
            )

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

    return _inspect_skill_bundle(upload_bytes)


def _inspect_skill_bundle(
    bundle_bytes: bytes, *, stored: bool = False
) -> SkillBundleInspectResponse:
    normalized = (
        normalize_custom_bundle(
            bundle_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
        )
        if stored
        else normalize_custom_bundle(bundle_bytes)
    )
    with ZipIndex(normalized.content) as bundle_zip:
        document = parse_skill_document(
            bundle_zip.read(SKILL_MD_NAME),
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
    *,
    before_version: Annotated[int | None, Query(ge=1)] = None,
) -> list[SkillVersionResponse]:
    """Return up to 50 versions. Use the last version number to read older rows."""
    skill = fetch_skill(
        skill_id, policy=SkillManagementPolicy.EDIT, user=user, db_session=db_session
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return [
        SkillVersionResponse(
            id=version.id,
            version_number=version.version_number,
            created_at=version.created_at,
            created_by=(
                MinimalUserSnapshot(id=creator.id, email=creator.email)
                if creator is not None
                else None
            ),
            is_current=is_current,
            has_bundle=version.bundle_file_id is not None,
        )
        for version, creator, is_current in list_skill_versions(
            skill, db_session, before_version=before_version
        )
    ]


@user_router.get("/custom/{skill_id}/versions/{version_id}")
def preview_custom_skill_version(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillBundleInspectResponse:
    skill = fetch_skill(
        skill_id, policy=SkillManagementPolicy.EDIT, user=user, db_session=db_session
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    version = fetch_skill_version(skill, version_id, db_session)
    return _inspect_skill_bundle(
        read_stored_version_bundle(skill, version, get_default_file_store()),
        stored=True,
    )


@user_router.post("/custom/{skill_id}/versions/{version_id}/restore")
def restore_custom_skill_version(
    skill_id: UUID,
    version_id: UUID,
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
    version = fetch_skill_version(skill, version_id, db_session)
    source = (version.id, version.bundle_file_id)
    return _replace_skill_bundle_from_editor(
        skill,
        read_stored_version_bundle(skill, version, get_default_file_store()),
        user,
        db_session,
        stored=True,
        restored_version=source,
    )


@user_router.put("/custom/{skill_id}/bundle")
def replace_current_user_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
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

    file_store = get_default_file_store()
    with _commit_skill_bundle(
        read_bundle_file(bundle.file, filename=bundle.filename),
        bundle.filename,
        file_store,
        db_session,
        expected_name=skill.name,
    ) as ingested:
        skill, user = _lock_skill_after_storage(skill.id, user, db_session)
        stale_file_ids = replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            creator_id=user.id,
            db_session=db_session,
        )

    delete_unreferenced_skill_bundles(stale_file_ids, db_session)
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

    observed: list[SkillContentSnapshot] = []

    def read_existing() -> bytes:
        # Only a merge depends on the current content; a full replacement does not.
        observed.append(skill_content_snapshot(skill))
        return read_custom_skill_bundle_bytes(skill)

    updated_bundle_bytes = update_custom_bundle_files(
        read_existing,
        read_bundle_file(upload.file, filename=upload.filename),
        filename=upload.filename,
    )
    return _replace_skill_bundle_from_editor(
        skill,
        updated_bundle_bytes,
        user,
        db_session,
        expected_content=observed[0] if observed else None,
        edited=True,
    )


@user_router.delete("/custom/{skill_id}/files")
def remove_current_user_skill_file(
    skill_id: UUID,
    path: str,
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
    if not path:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Skill file path cannot be empty")

    expected_content = skill_content_snapshot(skill)
    updated_bundle_bytes = update_custom_bundle_files(
        read_custom_skill_bundle_bytes(skill),
        remove_path=path,
    )
    return _replace_skill_bundle_from_editor(
        skill,
        updated_bundle_bytes,
        user,
        db_session,
        expected_content=expected_content,
        edited=True,
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
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if (
        "public_permission" in patch_req.model_fields_set
        and patch_req.public_permission != skill.public_permission
    ):
        ensure_can_edit_org_visibility(user)
    if not (patch_req.has_details_update or patch_req.has_db_field_update):
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    expected_content = skill_content_snapshot(skill)
    file_store = get_default_file_store() if patch_req.has_details_update else None
    new_bundle_file_id: str | None = None
    stale_file_ids: list[str] = []
    commit_attempted = False

    try:
        if file_store is not None:
            old_bundle_bytes = read_custom_skill_bundle_bytes(skill, file_store)
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
                # The SKILL.md rewrite keeps every other stored path unchanged.
                uncapped_paths=EVERY_PATH,
            )
            new_bundle_file_id = ingested.bundle_file_id
            skill, user = _lock_skill_after_storage(
                skill.id, user, db_session, expected_content
            )
            stale_file_ids = replace_skill_bundle(
                skill=skill,
                ingested=ingested,
                creator_id=user.id,
                db_session=db_session,
            )
        else:
            skill, user = _lock_skill_after_storage(skill.id, user, db_session)

        old_public_permission = skill.public_permission
        before_affected = affected_user_ids_for_skill(skill, db_session)
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

        commit_attempted = True
        db_session.commit()
    except Exception:
        db_session.rollback()
        if (
            not commit_attempted
            and file_store is not None
            and new_bundle_file_id is not None
        ):
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    delete_unreferenced_skill_bundles(stale_file_ids, db_session)

    db_session.expire(skill)
    visibility_changed = old_public_permission != skill.public_permission
    if patch_req.has_details_update or visibility_changed:
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
    skill, user = _lock_skill_after_storage(skill_id, user, db_session)
    if (
        share_req.user_shares is None
        and share_req.group_shares is None
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
    user = lock_resource_access_user(user.id, db_session)
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

    if skill.author_user_id != user.id and not (
        has_global_permission(user, Permission.MANAGE_SKILLS)
        and skill_ownership_is_vacant(skill)
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
    user = lock_resource_access_user(user.id, db_session)
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
    delete_unreferenced_skill_bundles(file_ids, db_session)
