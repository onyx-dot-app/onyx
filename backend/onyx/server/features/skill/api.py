import io
import zipfile
from contextlib import ExitStack
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import get_effective_permissions, require_permission
from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session, get_session_with_tenant
from onyx.db.enums import (
    AccountType,
    ExternalAppType,
    Permission,
    SkillSharePermission,
)
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    get_built_in_external_app,
    get_external_app_by_id,
)
from onyx.db.models import Skill, User
from onyx.db.skill import (
    SkillManagementPolicy,
    add_new_skill__no_commit,
    affected_user_ids_for_skill,
    delete_skill,
    enable_new_skill_if_name_available__no_commit,
    fetch_skill,
    list_skills,
    replace_skill_bundle,
    replace_skill_shares,
    set_skill_enabled_for_user,
    set_skill_public_permission,
    transfer_skill_ownership,
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import (
    GitHubImportedSkill,
    GitHubSkillNotImported,
    GitHubSkillPreview,
    GitHubSkillsImportRequest,
    GitHubSkillsImportResponse,
    GitHubSkillsPreviewRequest,
    GitHubSkillsPreviewResponse,
    SkillBundleInspectResponse,
    SkillCreateRequest,
    SkillEditableDetailResponse,
    SkillEnableRequest,
    SkillPatchRequest,
    SkillPreviewResponse,
    SkillResponse,
    SkillShareRequest,
    SkillsList,
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
    compute_bundle_sha256,
    inspect_custom_bundle,
    normalize_custom_bundle,
    read_bundle_file,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    update_custom_bundle_files,
)
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.ingest import (
    delete_bundle_blob,
    ingested_skill_bundle,
    save_skill_bundle_bytes,
)
from onyx.skills.ingest_from_github import fetch_github_skill_bundles
from onyx.skills.metadata import parse_skill_document
from onyx.skills.push import push_skill_to_affected_sandboxes, push_skills_for_users
from shared_configs.contextvars import get_current_tenant_id

user_router = APIRouter(prefix="/skills")


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


def _ensure_can_edit_org_visibility(skill: Skill, user: User) -> None:
    if skill.author_user_id == user.id:
        return
    if user.role == UserRole.ADMIN:
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You do not have permission to change organization-wide skill access.",
    )


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


def _replace_skill_bundle_from_editor(
    skill: Skill,
    bundle_bytes: bytes,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    file_store = get_default_file_store()
    with ingested_skill_bundle(
        bundle_bytes,
        f"{skill.name}.zip",
        file_store,
        expected_name=skill.name,
    ) as ingested:
        old_file_id = replace_skill_bundle(
            skill=skill,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    db_session.commit()
    delete_bundle_blob(file_store, old_file_id)
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
        read_bundle_file(bundle.file),
        bundle.filename,
        file_store,
    ) as ingested:
        skill = add_new_skill__no_commit(
            Skill(
                name=ingested.canonical_name,
                description=ingested.description,
                bundle_file_id=ingested.bundle_file_id,
                bundle_sha256=ingested.bundle_sha256,
                is_valid=True,
                author_user_id=user.id,
            ),
            db_session,
        )
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
    selected_paths = list(dict.fromkeys(request.paths))
    not_imported: list[GitHubSkillNotImported] = []
    created: list[tuple[Skill, bool]] = []

    file_store = get_default_file_store()
    with ExitStack() as ingested_bundles:
        for path in selected_paths:
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

            ingested = ingested_bundles.enter_context(
                ingested_skill_bundle(
                    selected_skill.bundle_bytes,
                    f"{selected_skill.name}.zip",
                    file_store,
                    expected_name=selected_skill.name,
                )
            )
            skill = add_new_skill__no_commit(
                Skill(
                    name=ingested.canonical_name,
                    description=ingested.description,
                    bundle_file_id=ingested.bundle_file_id,
                    bundle_sha256=ingested.bundle_sha256,
                    is_valid=True,
                    author_user_id=user.id,
                ),
                db_session,
            )
            enabled = enable_new_skill_if_name_available__no_commit(
                skill,
                user.id,
                db_session,
            )
            created.append((skill, enabled))
        db_session.commit()

    if any(enabled for _, enabled in created):
        push_skills_for_users({user.id}, db_session)
        db_session.commit()

    return GitHubSkillsImportResponse(
        imported=[
            GitHubImportedSkill(
                skill=skill_response_for_user(
                    skill,
                    user,
                    db_session,
                    include_share_details=True,
                ),
                disabled_reason=(
                    None
                    if enabled
                    else f"Another skill named “{skill.name}” is already enabled."
                ),
            )
            for skill, enabled in created
        ],
        not_imported=not_imported,
    )


@user_router.post("/custom/editor")
def create_custom_skill_from_editor(
    name: Annotated[str, Form(min_length=1)],
    description: Annotated[str, Form(min_length=1)],
    instructions_markdown: Annotated[str, Form(min_length=1)],
    upload: Annotated[UploadFile | None, File()] = None,
    auto_enable: Annotated[bool, Form()] = True,
    external_app_id: Annotated[int | None, Form(gt=0)] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    if external_app_id is not None:
        if (
            user.role != UserRole.ADMIN
            and Permission.FULL_ADMIN_PANEL_ACCESS
            not in get_effective_permissions(user)
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Only administrators can create a skill for an external app.",
            )
        if get_external_app_by_id(db_session, external_app_id) is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "External app not found.")

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
            read_bundle_file(upload.file),
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
        skill = add_new_skill__no_commit(
            Skill(
                name=ingested.canonical_name,
                description=ingested.description,
                bundle_file_id=ingested.bundle_file_id,
                bundle_sha256=ingested.bundle_sha256,
                is_valid=True,
                author_user_id=user.id,
            ),
            db_session,
        )
        if external_app_id is not None:
            associate_custom_skill_with_external_app__no_commit(
                db_session,
                external_app_id=external_app_id,
                skill_id=skill.id,
            )
        if should_auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{skill.name}' is already enabled.",
            )
        db_session.commit()

    if should_auto_enable:
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

    upload_bytes = read_bundle_file(upload.file)
    if upload.filename.lower() == SKILL_MD_NAME.lower():
        upload_bytes = build_single_file_bundle(SKILL_MD_NAME, upload_bytes)
    elif not upload.filename.lower().endswith(".zip"):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "upload must be SKILL.md or a ZIP containing SKILL.md",
        )

    normalized = normalize_custom_bundle(upload_bytes)
    with zipfile.ZipFile(io.BytesIO(normalized.content)) as bundle_zip:
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
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file),
        bundle.filename,
        file_store,
        expected_name=skill.name,
    ) as ingested:
        old_file_id = replace_skill_bundle(
            skill=skill,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    db_session.commit()
    delete_bundle_blob(file_store, old_file_id)
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
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    existing_bundle_bytes = read_custom_skill_bundle_bytes(skill)
    updated_bundle_bytes = update_custom_bundle_files(
        existing_bundle_bytes,
        read_bundle_file(upload.file),
        filename=upload.filename,
    )
    return _replace_skill_bundle_from_editor(
        skill, updated_bundle_bytes, user, db_session
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
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if not path:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Skill file path cannot be empty")

    updated_bundle_bytes = update_custom_bundle_files(
        read_custom_skill_bundle_bytes(skill),
        remove_path=path,
    )
    return _replace_skill_bundle_from_editor(
        skill, updated_bundle_bytes, user, db_session
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
        _ensure_can_edit_org_visibility(skill, user)
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
    old_bundle_file_id: str | None = None

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
            new_bundle_file_id = save_skill_bundle_bytes(
                new_bundle_bytes,
                display_name=f"{skill.name}.zip",
                file_store=file_store,
            )
            old_bundle_file_id = replace_skill_bundle(
                skill=skill,
                new_bundle_file_id=new_bundle_file_id,
                new_bundle_sha256=compute_bundle_sha256(new_bundle_bytes),
                new_description=description,
                db_session=db_session,
            )

        if patch_req.has_db_field_update:
            public_permission = (
                patch_req.public_permission
                if "public_permission" in patch_req.model_fields_set
                else None
            )
            set_skill_public_permission(
                skill=skill,
                public_permission=public_permission,
                db_session=db_session,
            )

        db_session.commit()
    except Exception:
        if file_store is not None and new_bundle_file_id is not None:
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    db_session.expire(skill)
    visibility_changed = old_public_permission != skill.public_permission
    if patch_req.has_details_update or visibility_changed:
        after_affected = affected_user_ids_for_skill(skill, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)
        db_session.commit()

    if file_store is not None and old_bundle_file_id is not None:
        delete_bundle_blob(file_store, old_bundle_file_id)
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


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
        and "public_permission" not in share_req.model_fields_set
    ):
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    touches_org_visibility = "public_permission" in share_req.model_fields_set
    if touches_org_visibility:
        _ensure_can_edit_org_visibility(skill, user)

    before_affected = affected_user_ids_for_skill(skill, db_session)
    if touches_org_visibility:
        set_skill_public_permission(
            skill=skill,
            public_permission=share_req.public_permission,
            db_session=db_session,
        )

    user_shares: dict[UUID, SkillSharePermission] | None = None
    if share_req.user_shares is not None:
        user_shares = {
            user_share.user_id: user_share.permission
            for user_share in share_req.user_shares
            if user_share.user_id != skill.author_user_id
        }

    group_shares: dict[int, SkillSharePermission] | None = None
    if share_req.group_shares is not None:
        group_shares = {
            group_share.group_id: group_share.permission
            for group_share in share_req.group_shares
        }

    replace_skill_shares(
        skill=skill,
        user_shares=user_shares,
        group_shares=group_shares,
        db_session=db_session,
    )

    db_session.commit()
    db_session.expire(skill)
    after_affected = affected_user_ids_for_skill(skill, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)
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
        user.role == UserRole.ADMIN and ownership_vacant
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
    if target.role in [UserRole.SLACK_USER, UserRole.EXT_PERM_USER, UserRole.LIMITED]:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership cannot be transferred to this account type.",
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

    db_session.commit()
    db_session.expire(skill)
    after_affected = affected_user_ids_for_skill(skill, db_session)
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

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    db_session.commit()
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)
