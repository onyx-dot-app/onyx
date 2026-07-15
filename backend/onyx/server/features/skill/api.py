import io
import zipfile
from contextlib import ExitStack
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import AccountType
from onyx.db.enums import ExternalAppType
from onyx.db.enums import Permission
from onyx.db.enums import SkillSharePermission
from onyx.db.external_app import get_built_in_external_app
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import create_skill__no_commit
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill
from onyx.db.skill import list_skills
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_shares
from onyx.db.skill import SkillAccessPolicy
from onyx.db.skill import transfer_skill_ownership
from onyx.db.skill import update_skill_fields
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import GitHubSkillPreview
from onyx.server.features.skill.models import GitHubSkillsImportRequest
from onyx.server.features.skill.models import GitHubSkillsPreviewRequest
from onyx.server.features.skill.models import GitHubSkillsPreviewResponse
from onyx.server.features.skill.models import SkillBundleInspectResponse
from onyx.server.features.skill.models import SkillCreateRequest
from onyx.server.features.skill.models import SkillEditableDetailResponse
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillShareRequest
from onyx.server.features.skill.models import SkillsList
from onyx.server.features.skill.models import TransferSkillOwnershipRequest
from onyx.server.features.skill.response_helpers import skill_preview_response
from onyx.server.features.skill.response_helpers import skill_response_for_user
from onyx.server.features.skill.response_helpers import skills_list_response_for_user
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import build_single_file_bundle
from onyx.skills.bundle import build_skill_md
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import inspect_custom_bundle
from onyx.skills.bundle import parse_skill_md_metadata
from onyx.skills.bundle import read_bundle_file
from onyx.skills.bundle import read_custom_bundle_instructions
from onyx.skills.bundle import rewrite_custom_bundle_skill_md
from onyx.skills.bundle import SKILL_MD_NAME
from onyx.skills.bundle import slug_from_filename
from onyx.skills.bundle import slug_from_skill_name
from onyx.skills.bundle import update_custom_bundle_files
from onyx.skills.bundle import validate_and_normalize_custom_bundle
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.github_import import fetch_github_skill_bundles
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingested_skill_bundle
from onyx.skills.ingest import save_skill_bundle_bytes
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from shared_configs.contextvars import get_current_tenant_id

user_router = APIRouter(prefix="/skills")


def _github_authorization_header(user: User) -> str | None:
    tenant_id = get_current_tenant_id()
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        github_app = get_built_in_external_app(db_session, ExternalAppType.GITHUB)
        if (
            github_app is None
            or fetch_skill(
                github_app.skill_id,
                policy=SkillAccessPolicy.USE,
                user=user,
                db_session=db_session,
            )
            is None
        ):
            return None
        github_app_id = github_app.id

    ensure_fresh_credentials(tenant_id, github_app_id, user.id)
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        return resolve_injection_headers(db_session, github_app_id, user.id).get(
            "Authorization"
        )


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
        f"{skill.slug}.zip",
        file_store,
        slug=skill.slug,
    ) as ingested:
        old_file_id = replace_skill_bundle(
            skill=skill,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    delete_bundle_blob(file_store, old_file_id)
    return _editable_skill_response(skill, user, db_session)


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list_skills(
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    return skills_list_response_for_user(rows, user, db_session)


@user_router.get("/{skill_id}")
def fetch_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.VIEW,
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
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_preview_response(skill)


@user_router.post("/custom")
def create_custom_skill(
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    if bundle.filename is not None and bundle.filename.lower().endswith(".zip"):
        slug = slug_from_filename(bundle.filename)
        if slug in BUILT_IN_SKILLS:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"slug '{slug}' is reserved",
            )

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file),
        bundle.filename,
        file_store,
    ) as ingested:
        skill = create_skill__no_commit(
            slug=ingested.slug,
            name=ingested.name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_public=False,
            author_user_id=user.id,
            db_session=db_session,
        )
        db_session.commit()

    push_skill_to_affected_sandboxes(skill, db_session)
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.post("/custom/editor")
def create_custom_skill_from_editor(
    name: Annotated[str, Form(min_length=1)],
    description: Annotated[str, Form(min_length=1)],
    instructions_markdown: Annotated[str, Form(min_length=1)],
    upload: Annotated[UploadFile | None, File()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
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
    provisional_slug = slug_from_skill_name(create_request.name)
    bundle_bytes = validate_and_normalize_custom_bundle(
        bundle_bytes, slug=provisional_slug
    )
    if upload is not None:
        bundle_bytes = update_custom_bundle_files(
            bundle_bytes,
            read_bundle_file(upload.file),
            filename=upload.filename,
            slug=provisional_slug,
        )
    bundle_bytes = rewrite_custom_bundle_skill_md(
        bundle_bytes,
        slug=provisional_slug,
        name=create_request.name,
        description=create_request.description,
        instructions_markdown=create_request.instructions_markdown,
    )
    file_store = get_default_file_store()
    with ingested_skill_bundle(
        bundle_bytes,
        f"{provisional_slug}.zip",
        file_store,
        slug=provisional_slug,
    ) as ingested:
        skill = create_skill__no_commit(
            slug=ingested.slug,
            name=ingested.name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_public=False,
            author_user_id=user.id,
            db_session=db_session,
        )
        db_session.commit()

    push_skill_to_affected_sandboxes(skill, db_session)
    return _editable_skill_response(skill, user, db_session)


@user_router.post("/github/preview")
def preview_github_skills(
    request: GitHubSkillsPreviewRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> GitHubSkillsPreviewResponse:
    repository, skills = fetch_github_skill_bundles(
        request.repository,
        _github_authorization_header(user),
    )
    if repository.ref is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "GitHub did not return a repository revision.",
        )
    return GitHubSkillsPreviewResponse(
        repository=f"{repository.owner}/{repository.repo}",
        revision=repository.ref,
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
) -> list[SkillResponse]:
    _, available_skills = fetch_github_skill_bundles(
        request.repository,
        _github_authorization_header(user),
        revision=request.revision,
        subpath=request.subpath,
    )
    skills_by_path = {skill.path: skill for skill in available_skills}
    selected_paths = list(dict.fromkeys(request.paths))
    missing_paths = [path for path in selected_paths if path not in skills_by_path]
    if missing_paths:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"These skills are no longer available in the repository: {', '.join(missing_paths)}. Search the repository again.",
        )
    selected_skills = [skills_by_path[path] for path in selected_paths]
    unavailable_reason = next(
        (
            skill.unavailable_reason
            for skill in selected_skills
            if skill.unavailable_reason is not None
        ),
        None,
    )
    if unavailable_reason is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            unavailable_reason,
        )
    slugs = [skill.slug for skill in selected_skills]
    if len(slugs) != len(set(slugs)):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Two or more selected skills have the same name. Rename one in SKILL.md, then try again.",
        )

    file_store = get_default_file_store()
    created_skills: list[Skill] = []
    with ExitStack() as ingested_bundles:
        for selected_skill in selected_skills:
            if selected_skill.bundle_bytes is None:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Skill at '{selected_skill.path}' cannot be imported.",
                )
            ingested = ingested_bundles.enter_context(
                ingested_skill_bundle(
                    selected_skill.bundle_bytes,
                    f"{selected_skill.slug}.zip",
                    file_store,
                    slug=selected_skill.slug,
                )
            )
            try:
                skill = create_skill__no_commit(
                    slug=ingested.slug,
                    name=ingested.name,
                    description=ingested.description,
                    bundle_file_id=ingested.bundle_file_id,
                    bundle_sha256=ingested.bundle_sha256,
                    is_public=False,
                    author_user_id=user.id,
                    db_session=db_session,
                )
            except OnyxError as exc:
                if exc.error_code == OnyxErrorCode.DUPLICATE_RESOURCE:
                    raise OnyxError(
                        OnyxErrorCode.DUPLICATE_RESOURCE,
                        f'A skill named "{selected_skill.name}" already exists in this workspace. Rename it in SKILL.md, then try again.',
                    ) from exc
                raise
            created_skills.append(skill)
        db_session.commit()

    push_skills_for_users({user.id}, db_session)
    return [
        skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )
        for skill in created_skills
    ]


@user_router.get("/custom/{skill_id}/edit")
def fetch_custom_skill_for_edit(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
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

    normalized_bundle = validate_and_normalize_custom_bundle(
        upload_bytes,
        slug="bundle-preview",
    )
    with zipfile.ZipFile(io.BytesIO(normalized_bundle)) as bundle_zip:
        name, description = parse_skill_md_metadata(bundle_zip.read(SKILL_MD_NAME))
    contents = inspect_custom_bundle(normalized_bundle)
    return SkillBundleInspectResponse(
        name=name,
        description=description,
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
        policy=SkillAccessPolicy.EDIT,
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
        slug=skill.slug,
    ) as ingested:
        old_file_id = replace_skill_bundle(
            skill=skill,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
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
        policy=SkillAccessPolicy.EDIT,
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
        slug=skill.slug,
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
        policy=SkillAccessPolicy.EDIT,
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
        slug=skill.slug,
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
        policy=SkillAccessPolicy.EDIT,
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

    old_visibility = (skill.public_permission, skill.enabled)
    before_affected = affected_user_ids_for_skill(skill, db_session)
    file_store = get_default_file_store() if patch_req.has_details_update else None
    new_bundle_file_id: str | None = None
    old_bundle_file_id: str | None = None

    try:
        if file_store is not None:
            old_bundle_bytes = read_custom_skill_bundle_bytes(skill, file_store)
            name = patch_req.name if patch_req.name is not None else skill.name
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
                slug=skill.slug,
                name=name,
                description=description,
                instructions_markdown=instructions_markdown,
            )
            new_bundle_file_id = save_skill_bundle_bytes(
                new_bundle_bytes,
                display_name=f"{skill.slug}.zip",
                file_store=file_store,
            )
            old_bundle_file_id = replace_skill_bundle(
                skill=skill,
                new_bundle_file_id=new_bundle_file_id,
                new_bundle_sha256=compute_bundle_sha256(new_bundle_bytes),
                new_name=name,
                new_description=description,
                db_session=db_session,
            )

        if patch_req.has_db_field_update:
            public_permission = (
                patch_req.public_permission
                if "public_permission" in patch_req.model_fields_set
                else None
            )
            is_public = (
                public_permission is not None
                if "public_permission" in patch_req.model_fields_set
                else None
            )
            enabled = (
                patch_req.enabled if "enabled" in patch_req.model_fields_set else None
            )
            update_skill_fields(
                skill=skill,
                is_public=is_public,
                public_permission=public_permission,
                enabled=enabled,
                db_session=db_session,
            )

        db_session.commit()
    except Exception:
        if file_store is not None and new_bundle_file_id is not None:
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    db_session.expire(skill)
    visibility_changed = old_visibility != (
        skill.public_permission,
        skill.enabled,
    )
    if patch_req.has_details_update or visibility_changed:
        after_affected = affected_user_ids_for_skill(skill, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)

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
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
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
        update_skill_fields(
            skill=skill,
            is_public=share_req.public_permission is not None,
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
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot change ownership.",
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
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)
