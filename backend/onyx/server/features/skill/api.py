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
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Plugin, Skill, User
from onyx.db.plugin import (
    ORGANIZATION_LIBRARY_ID,
    check_sharing_allowed,
    find_upload_target,
    free_plugin_name,
    get_organization_library_default,
    get_plugin_current_version_id,
    get_plugin_version,
    get_stored_version_content,
    get_user_uploads_id,
    get_version_manifest,
    get_versions_needs,
    list_plugin_versions,
    lock_plugin,
    next_version_number,
    refuse_if_synced,
    set_marketplace_default__no_commit,
    version_is_skill,
)
from onyx.db.plugin_access import affected_user_ids_for_plugins, get_version_user_runs
from onyx.db.skill import (
    SkillSharingChange,
    add_uploaded_plugin_version__no_commit,
    approve_skill_review__no_commit,
    bulk_share_skills__no_commit,
    bulk_update_skill__no_commit,
    create_custom_skill__no_commit,
    create_skill_from_bundle__no_commit,
    create_uploaded_plugin__no_commit,
    delete_skill_for_user__no_commit,
    deny_skill_review__no_commit,
    enable_new_skill_if_name_available__no_commit,
    ensure_can_edit_org_visibility,
    fetch_editable_skill,
    fetch_new_skill_owner,
    fetch_skill,
    is_published,
    list_chat_skills,
    list_review_requests,
    list_skills,
    lock_skill_for_save,
    publish_skill__no_commit,
    replace_skill_bundle,
    restore_plugin_version__no_commit,
    set_skill_enabled_for_user,
    share_skill__no_commit,
    skill_enabled_for_user,
    skill_name_conflicts,
    transfer_skill_ownership,
)
from onyx.db.skill_limit import lock_user_skill_preferences, users_past_write_limit
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.integrations.plugin_needs import (
    integrations_for_needs,
    need_views,
    needs_of_versions,
    turn_on_needed_integrations__no_commit,
)
from onyx.integrations.service import reload_craft_sessions
from onyx.microvm.configs import HARNESS_SANDBOX_ENABLED
from onyx.server.features.skill.models import (
    GitHubImportedSkill,
    GitHubSkillNotImported,
    GitHubSkillsImportResponse,
    OrganizationLibraryDefaultAccess,
    PluginSkillInstructions,
    PluginUploadPreview,
    PluginUploadResponse,
    PluginUploadSkill,
    PluginUploadTarget,
    SkillBulkActionRequest,
    SkillBulkFailure,
    SkillBulkResponse,
    SkillBulkShareRequest,
    SkillBundleInspectResponse,
    SkillCreateRequest,
    SkillEditableDetailResponse,
    SkillEnableRequest,
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
    plugin_version_detail,
    skill_preview_response,
    skill_response_for_user,
    skills_list_response_for_user,
)
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    build_single_file_bundle,
    build_skill_md,
    bundle_files_from_manifest,
    check_skill_md_size,
    compute_bundle_manifest,
    inspect_custom_bundle,
    normalize_custom_bundle,
    open_bundle_zip,
    read_bundle_file,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    strip_skill_md_frontmatter,
    update_custom_bundle_files,
)
from onyx.skills.content import (
    read_skill_bundle_blob,
    read_version_contents,
    read_versions_skill_md,
)
from onyx.skills.ingest import (
    IngestedBundle,
    delete_bundle_blob,
    ingest_skill_bundle,
    ingested_skill_bundle,
    stored_plugin_bundle,
)
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES, SKILL_WRITE_MAX_FILES
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import (
    GITHUB_SKILL_MAX_COUNT,
    ChatSkill,
    PluginBundle,
    PluginManifest,
    SkillBundleFile,
)
from onyx.skills.plugin_bundle import read_plugin_bundle
from onyx.skills.push import (
    commit_push_state,
    push_skill_to_affected_sandboxes,
    push_skills_and_commit,
)

user_router = APIRouter(prefix="/skills")

_BUNDLE_CLEANUP = "skill bundle cleanup"


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
    created: list[tuple[Plugin, bool]] = []
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
                        path=source.path, name=source.name, reason=exc.detail
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
    push_skills_and_commit(affected, db_session)
    return _import_response(created, not_imported, auto_enable, user, db_session)


def _import_response(
    created: list[tuple[Plugin, bool]],
    not_imported: list[GitHubSkillNotImported],
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> GitHubSkillsImportResponse:
    imported: list[GitHubImportedSkill] = []
    for skill, enabled in created:
        response = skill_response_for_user(
            skill, user, db_session, include_share_details=True
        )
        imported.append(
            GitHubImportedSkill(
                skill=response,
                disabled_reason=(
                    f"Another skill named “{response.name}” is already enabled."
                    if auto_enable and not enabled
                    else None
                ),
            )
        )
    return GitHubSkillsImportResponse(imported=imported, not_imported=not_imported)


def _skill_name(skill: Plugin, db_session: Session) -> str:
    """A skill name never changes, so the current version holds it."""
    name = get_stored_version_content(skill.current_version_id, db_session).name
    if name is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return name


def _bundle_to_edit(skill: Plugin, user: User, db_session: Session) -> bytes:
    """The bundle of the version an edit starts from. Takes the save locks,
    the order of every save and toggle, and holds them to the save, so the
    current version cannot move under the edit."""
    lock_skill_for_save(skill, user, db_session)
    stored = get_stored_version_content(skill.current_version_id, db_session)
    return read_skill_bundle_blob(
        stored.bundle_file_id, stored.name or str(skill.current_version_id)
    )


def _editable_skill_response(
    skill: Plugin,
    user: User,
    db_session: Session,
    version_id: UUID | None = None,
) -> SkillEditableDetailResponse:
    """The skill at ``version_id``, by default its current version. A write
    passes the version it made, so a caller that chains writes bases the next
    one on that version and not on a newer save by someone else."""
    if version_id is None:
        version_id = get_plugin_current_version_id(skill.id, db_session)
    if version_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill has no plugin version.")
    is_skill = version_is_skill(version_id, db_session)
    response = skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
        shown_version_id=version_id,
        include_plugin_detail=not is_skill,
    )
    if not is_skill:
        return SkillEditableDetailResponse(
            **response.model_dump(),
            instructions_markdown="",
            files=_version_files(version_id, db_session),
        )
    bundle_contents = read_version_contents(version_id, db_session)
    return SkillEditableDetailResponse(
        **response.model_dump(),
        instructions_markdown=bundle_contents.instructions_markdown,
        files=bundle_contents.files,
    )


def _version_files(version_id: UUID, db_session: Session) -> list[SkillBundleFile]:
    file_manifest = get_stored_version_content(version_id, db_session).file_manifest
    return bundle_files_from_manifest(file_manifest or [])


def _replace_skill_bundle_from_editor(
    skill: Plugin,
    bundle_bytes: bytes,
    base_version_id: UUID | None,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    """Save an editor file change as a new plugin version. A change that leaves
    the files as they are adds no version."""
    file_store = get_default_file_store()
    name = _skill_name(skill, db_session)
    with ingested_skill_bundle(
        bundle_bytes,
        f"{name}.zip",
        file_store,
        expected_name=name,
        # update_custom_bundle_files applied the limits that fit each edit.
        upload_limits=False,
    ) as ingested:
        version = replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            base_version_id=base_version_id,
            user=user,
            skip_if_unchanged=True,
            previous_manifest=lambda: compute_bundle_manifest(
                _bundle_to_edit(skill, user, db_session)
            ),
            db_session=db_session,
        )
        created_version_id = version.id if version is not None else None
        db_session.commit()

    if created_version_id is None:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        return _editable_skill_response(skill, user, db_session, base_version_id)
    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    commit_push_state(db_session)
    return _editable_skill_response(skill, user, db_session, created_version_id)


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list_skills(user=user, db_session=db_session)
    return skills_list_response_for_user(rows, user, db_session)


@user_router.get("/chat")
def list_chat_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ChatSkill]:
    """The skills that the user's chat agents get, for the `@` picker. Built-ins
    are in it when the deployment has chat VMs."""
    return list_chat_skills(db_session, user, with_sandbox=HARNESS_SANDBOX_ENABLED)


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
    integrations_changed = False
    if isinstance(request, SkillBulkShareRequest):
        shared = bulk_share_skills__no_commit(
            request.skill_ids, request.sharing.to_change(), user, db_session
        )
        succeeded = shared.succeeded
        failed = [
            SkillBulkFailure(skill_id=skill_id, detail=detail)
            for skill_id, detail in shared.failed
        ]
        affected = shared.affected_user_ids
    else:
        for skill_id in sorted(set(request.skill_ids)):
            try:
                with db_session.begin_nested():
                    item_affected, item_file_ids = bulk_update_skill__no_commit(
                        skill_id, request.action, user, db_session
                    )
                    turned_on = (
                        request.action == "enable"
                        and _turn_on_needs__no_commit(skill_id, user, db_session)
                    )
            except OnyxError as exc:
                failed.append(SkillBulkFailure(skill_id=skill_id, detail=exc.detail))
                continue
            succeeded.append(skill_id)
            affected |= item_affected
            deleted_file_ids.extend(item_file_ids)
            integrations_changed |= turned_on
    db_session.commit()
    push_skills_and_commit(affected, db_session)
    if integrations_changed:
        reload_craft_sessions({user.id}, db_session)
    delete_files_best_effort(deleted_file_ids, context=_BUNDLE_CLEANUP)
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
    integrations_changed = request.enabled and _turn_on_needs__no_commit(
        skill.id, user, db_session
    )
    db_session.commit()
    push_skills_and_commit({user.id}, db_session)
    if integrations_changed:
        reload_craft_sessions({user.id}, db_session)
    return skill_response_for_user(
        skill, user, db_session, include_plugin_detail=isinstance(skill, Plugin)
    )


def _turn_on_needs__no_commit(skill_id: UUID, user: User, db_session: Session) -> bool:
    version_id = get_version_user_runs(skill_id, user.id, db_session)
    if version_id is None:
        return False
    return turn_on_needed_integrations__no_commit(
        user,
        get_versions_needs([version_id], db_session).get(version_id, []),
        db_session,
    )


@user_router.get("/review-requests")
def list_skill_review_requests(
    _: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> list[SkillReviewRequestResponse]:
    return [
        SkillReviewRequestResponse.model_validate(row, from_attributes=True)
        for row in list_review_requests(db_session)
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
    affected = set_marketplace_default__no_commit(
        ORGANIZATION_LIBRARY_ID, request.installation_policy, db_session
    )
    db_session.commit()
    push_skills_and_commit(affected, db_session)
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
        users=users_past_write_limit(db_session),
    )


@user_router.get("/{skill_id}")
def fetch_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(skill_id, user=user, db_session=db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_response_for_user(
        skill, user, db_session, include_plugin_detail=isinstance(skill, Plugin)
    )


@user_router.get("/{skill_id}/preview")
def preview_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillPreviewResponse:
    skill = fetch_skill(skill_id, user=user, db_session=db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill_preview_response(skill, user, db_session)


@user_router.get("/{skill_id}/plugin-skill")
def read_plugin_skill_for_current_user(
    skill_id: UUID,
    path: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PluginSkillInstructions:
    """The SKILL.md instructions of one skill in the plugin version the user
    runs."""
    skill = fetch_skill(skill_id, user=user, db_session=db_session)
    if not isinstance(skill, Plugin):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    version_id = get_version_user_runs(skill.id, user.id, db_session)
    if version_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    key = (version_id, path)
    skill_md = read_versions_skill_md([key], user.id, db_session).get(key)
    if skill_md is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "This skill could not be read.")
    return PluginSkillInstructions(
        instructions_markdown=strip_skill_md_frontmatter(skill_md)
    )


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
                f"A skill named '{ingested.canonical_name}' is already enabled.",
            )
        db_session.commit()

    if auto_enable:
        push_skill_to_affected_sandboxes(skill, db_session)
        commit_push_state(db_session)

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


def _read_plugin_upload(upload: UploadFile) -> PluginBundle:
    if not (upload.filename or "").lower().endswith(".zip"):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Upload a plugin as a .zip file.")
    return read_plugin_bundle(read_bundle_file(upload.file, filename=upload.filename))


def _bound_upload_target(
    plugin_id: UUID, name: str, user: User, db_session: Session
) -> Plugin:
    plugin = fetch_editable_skill(
        plugin_id, user=user, db_session=db_session, any_plugin=True
    )
    if plugin is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    refuse_if_synced(plugin)
    # Save as new and ownership transfer rename the plugin, not its plugin.json.
    manifest = (
        get_version_manifest(plugin.current_version_id, db_session)
        if plugin.current_version_id is not None
        else None
    )
    if name not in {plugin.name, manifest.name if manifest is not None else None}:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"This file holds the plugin {name}, not {plugin.name}. "
            f"Upload a file of {plugin.name}.",
        )
    return plugin


def _upload_target(
    bundle: PluginBundle,
    save_as_new: bool,
    plugin_id: UUID | None,
    user: User,
    db_session: Session,
) -> PluginUploadTarget:
    """``plugin_id`` binds the upload to that plugin: a new version of it.
    Without it, the manifest name picks the plugin (``find_upload_target``)."""
    name = bundle.manifest.name
    if save_as_new:
        target = None
    elif plugin_id is not None:
        target = _bound_upload_target(plugin_id, name, user, db_session)
    else:
        target = find_upload_target(name, user.id, db_session)
    if target is not None:
        return PluginUploadTarget(
            kind="new_version",
            plugin_id=target.id,
            plugin_name=target.name,
            version_number=next_version_number(target.id, db_session),
        )
    uploads_id = get_user_uploads_id(user.id, db_session)
    return PluginUploadTarget(
        kind="new_plugin",
        plugin_id=None,
        plugin_name=(
            free_plugin_name(uploads_id, name, db_session)
            if uploads_id is not None
            else name
        ),
        version_number=1,
    )


@user_router.post("/plugins/inspect")
def inspect_plugin_upload(
    bundle: UploadFile = File(...),
    save_as_new: Annotated[bool, Form()] = False,
    plugin_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PluginUploadPreview:
    plugin_bundle = _read_plugin_upload(bundle)
    target = _upload_target(plugin_bundle, save_as_new, plugin_id, user, db_session)
    name_conflicts = (
        []
        if target.plugin_id is not None
        else skill_name_conflicts(
            [skill.content.name for skill in plugin_bundle.skills],
            None,
            user,
            db_session,
        )
    )
    return PluginUploadPreview(
        manifest=plugin_bundle.manifest,
        skills=[
            PluginUploadSkill(
                path=skill.content.path,
                name=skill.content.name,
                description=skill.content.description,
                warnings=skill.warnings,
            )
            for skill in plugin_bundle.skills
        ],
        needs=need_views(plugin_bundle.needs, integrations_for_needs(user, db_session)),
        warnings=plugin_bundle.warnings,
        target=target,
        will_enable=(
            skill_enabled_for_user(target.plugin_id, user, db_session)
            if target.plugin_id is not None
            else not name_conflicts
        ),
        name_conflicts=name_conflicts,
    )


@user_router.post("/plugins")
def save_plugin_upload(
    bundle: UploadFile = File(...),
    save_as_new: Annotated[bool, Form()] = False,
    auto_enable: Annotated[bool, Form()] = True,
    plugin_id: Annotated[UUID | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PluginUploadResponse:
    plugin_bundle = _read_plugin_upload(bundle)
    file_store = get_default_file_store()
    added = True
    name_conflicts: list[str] = []
    with stored_plugin_bundle(plugin_bundle, file_store) as content:
        # Two uploads of one new name at the same time make one plugin with
        # two versions: the second one finds the first under the lock.
        lock_user_skill_preferences(user.id, db_session)
        target = _upload_target(plugin_bundle, save_as_new, plugin_id, user, db_session)
        if target.plugin_id is not None:
            plugin, version, added = add_uploaded_plugin_version__no_commit(
                target.plugin_id, content, user, db_session
            )
            target = target.model_copy(
                update={"version_number": version.version_number}
            )
            enabled = skill_enabled_for_user(plugin.id, user, db_session)
        else:
            plugin, enabled = create_uploaded_plugin__no_commit(
                content, auto_enable, user, db_session
            )
            target = target.model_copy(update={"plugin_name": plugin.name})
            if auto_enable and not enabled:
                name_conflicts = skill_name_conflicts(
                    [skill.content.name for skill in plugin_bundle.skills],
                    plugin.id,
                    user,
                    db_session,
                )
        integrations_changed = (
            added
            and enabled
            and turn_on_needed_integrations__no_commit(
                user, content.needs or [], db_session
            )
        )
        db_session.commit()
    if not added:
        delete_bundle_blob(file_store, content.bundle_file_id)

    db_session.expire(plugin)
    if added:
        push_skill_to_affected_sandboxes(plugin, db_session)
        commit_push_state(db_session)
    if integrations_changed:
        reload_craft_sessions({user.id}, db_session)
    return PluginUploadResponse(
        target=target,
        plugin=skill_response_for_user(
            plugin,
            user,
            db_session,
            include_share_details=True,
            include_plugin_detail=True,
        ),
        enabled=enabled,
        unchanged=not added,
        name_conflicts=name_conflicts,
    )


@user_router.post("/custom/editor")
def create_custom_skill_from_editor(
    name: Annotated[str, Form(min_length=1)],
    description: Annotated[str, Form(min_length=1)],
    instructions_markdown: Annotated[str, Form(min_length=1)],
    upload: Annotated[UploadFile | None, File()] = None,
    auto_enable: Annotated[bool, Form()] = True,
    sharing: Annotated[str | None, Form()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
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
        )
        if auto_enable and not enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"A skill named '{ingested.canonical_name}' is already enabled.",
            )
        db_session.commit()

    if auto_enable or share_request is not None:
        push_skill_to_affected_sandboxes(skill, db_session)
        commit_push_state(db_session)

    return _editable_skill_response(skill, user, db_session)


@user_router.get("/custom/{skill_id}/edit")
def fetch_custom_skill_for_edit(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = fetch_editable_skill(skill_id, user=user, db_session=db_session)
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


def _editable_skill(
    skill_id: UUID,
    user: User,
    db_session: Session,
    *,
    lock_for_update: bool,
    any_plugin: bool = False,
) -> Plugin:
    skill = fetch_editable_skill(
        skill_id,
        user=user,
        db_session=db_session,
        lock_for_update=lock_for_update,
        any_plugin=any_plugin,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill


@user_router.get("/custom/{skill_id}/versions")
def list_custom_skill_versions(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[SkillVersionResponse]:
    """Every version, newest first."""
    skill = fetch_editable_skill(
        skill_id, user=user, db_session=db_session, any_plugin=True
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return [
        SkillVersionResponse(
            id=version.id,
            version_number=version.version_number,
            created_at=version.created_at,
            created_by_email=version.created_by_email,
            is_current=is_current,
            review_status=(
                "published" if is_published else "pending" if is_pending else "draft"
            ),
            manifest_version=(
                PluginManifest.model_validate(version.manifest).version
                if version.manifest is not None
                else None
            ),
        )
        for version, is_current, is_published, is_pending in list_plugin_versions(
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
    skill = fetch_editable_skill(
        skill_id, user=user, db_session=db_session, any_plugin=True
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    get_plugin_version(skill.id, version_id, db_session)
    if not version_is_skill(version_id, db_session):
        detail = plugin_version_detail(
            version_id,
            needs_of_versions(user, [version_id], db_session).get(version_id, []),
            db_session,
        )
        return SkillVersionPreviewResponse(
            description=(
                detail.manifest.description or "" if detail.manifest is not None else ""
            ),
            instructions_markdown="",
            files=_version_files(version_id, db_session),
            plugin=detail,
        )
    stored = get_stored_version_content(version_id, db_session)
    contents = read_version_contents(version_id, db_session)
    return SkillVersionPreviewResponse(
        description=stored.description or "",
        instructions_markdown=contents.instructions_markdown,
        files=contents.files,
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
    skill = _editable_skill(
        skill_id, user, db_session, lock_for_update=False, any_plugin=True
    )
    get_plugin_version(skill.id, version_id, db_session)
    stored = get_stored_version_content(version_id, db_session)
    if not version_is_skill(version_id, db_session):
        return _restore_plugin_version(
            skill, stored.bundle_file_id, request.base_version_id, user, db_session
        )
    return _replace_skill_bundle_from_editor(
        skill,
        read_skill_bundle_blob(stored.bundle_file_id, stored.name or str(version_id)),
        request.base_version_id,
        user,
        db_session,
    )


def _restore_plugin_version(
    plugin: Plugin,
    bundle_file_id: str | None,
    base_version_id: UUID,
    user: User,
    db_session: Session,
) -> SkillEditableDetailResponse:
    file_store = get_default_file_store()
    bundle = read_plugin_bundle(
        read_skill_bundle_blob(bundle_file_id, plugin.name, file_store)
    )
    with stored_plugin_bundle(bundle, file_store) as content:
        version = restore_plugin_version__no_commit(
            plugin.id, content, base_version_id, user, db_session
        )
        created_version_id = version.id if version is not None else None
        db_session.commit()

    if created_version_id is None:
        delete_bundle_blob(file_store, content.bundle_file_id)
        return _editable_skill_response(plugin, user, db_session, base_version_id)
    db_session.expire(plugin)
    push_skill_to_affected_sandboxes(plugin, db_session)
    commit_push_state(db_session)
    return _editable_skill_response(plugin, user, db_session, created_version_id)


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
    skill = _editable_skill(
        skill_id, user, db_session, lock_for_update=True, any_plugin=True
    )
    affected = publish_skill__no_commit(
        skill, request.base_version_id, user, db_session
    )
    db_session.commit()
    db_session.expire(skill)
    push_skills_and_commit(affected, db_session)
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


@user_router.post("/custom/{skill_id}/versions/{version_id}/approve")
def approve_skill_review(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = _editable_skill(
        skill_id, user, db_session, lock_for_update=True, any_plugin=True
    )
    affected = approve_skill_review__no_commit(skill, version_id, db_session)
    db_session.commit()
    db_session.expire(skill)
    push_skills_and_commit(affected, db_session)
    return skill_response_for_user(skill, user, db_session, include_share_details=True)


@user_router.post("/custom/{skill_id}/versions/{version_id}/deny")
def deny_skill_review(
    skill_id: UUID,
    version_id: UUID,
    user: User = Depends(require_permission(Permission.MANAGE_PLUGINS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = _editable_skill(
        skill_id, user, db_session, lock_for_update=True, any_plugin=True
    )
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
    skill = _editable_skill(skill_id, user, db_session, lock_for_update=False)

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file, filename=bundle.filename),
        bundle.filename,
        file_store,
        expected_name=_skill_name(skill, db_session),
    ) as ingested:
        # An upload always adds a version, also for the same zip.
        replace_skill_bundle(
            skill=skill,
            ingested=ingested,
            base_version_id=base_version_id,
            user=user,
            skip_if_unchanged=False,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    commit_push_state(db_session)
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
    skill = _editable_skill(skill_id, user, db_session, lock_for_update=False)

    updated_bundle_bytes = update_custom_bundle_files(
        lambda: _bundle_to_edit(skill, user, db_session),
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
    skill = _editable_skill(skill_id, user, db_session, lock_for_update=False)
    if not path:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Skill file path cannot be empty")

    updated_bundle_bytes = update_custom_bundle_files(
        _bundle_to_edit(skill, user, db_session),
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
    skill = _editable_skill(skill_id, user, db_session, lock_for_update=False)
    if "public_permission" in patch_req.model_fields_set:
        ensure_can_edit_org_visibility(skill, user)
    if not (patch_req.has_details_update or patch_req.has_db_field_update):
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    was_published = is_published(skill, db_session)
    before_affected = affected_user_ids_for_plugins([skill.id], db_session)
    file_store = get_default_file_store() if patch_req.has_details_update else None
    new_bundle_file_id: str | None = None
    files_changed = False
    shown_version_id: UUID | None = None

    try:
        if file_store is not None:
            old_bundle_bytes = _bundle_to_edit(skill, user, db_session)
            stored = get_stored_version_content(skill.current_version_id, db_session)
            name = stored.name
            if name is None:
                raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
            description = (
                patch_req.description
                if patch_req.description is not None
                else stored.description or ""
            )
            instructions_markdown = patch_req.instructions_markdown
            if instructions_markdown is None:
                instructions_markdown = read_custom_bundle_instructions(
                    old_bundle_bytes
                )
            new_bundle_bytes = rewrite_custom_bundle_skill_md(
                old_bundle_bytes,
                canonical_name=name,
                description=description,
                instructions_markdown=instructions_markdown,
            )
            ingested = ingest_skill_bundle(
                new_bundle_bytes,
                f"{name}.zip",
                file_store,
                expected_name=name,
                upload_limits=False,
            )
            new_bundle_file_id = ingested.bundle_file_id
            created = replace_skill_bundle(
                skill=skill,
                ingested=ingested,
                base_version_id=patch_req.base_version_id,
                user=user,
                skip_if_unchanged=True,
                previous_manifest=lambda: compute_bundle_manifest(old_bundle_bytes),
                db_session=db_session,
            )
            files_changed = created is not None
            # The response names the version this save made, so a chained
            # edit cannot adopt a newer save by someone else.
            shown_version_id = (
                created.id if created is not None else patch_req.base_version_id
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

    if file_store is not None and new_bundle_file_id is not None and not files_changed:
        # Nothing references the bundle of an unchanged save.
        delete_bundle_blob(file_store, new_bundle_file_id)

    db_session.expire(skill)
    visibility_changed = was_published != is_published(skill, db_session)
    if files_changed or visibility_changed:
        after_affected = affected_user_ids_for_plugins([skill.id], db_session)
        push_skills_and_commit(before_affected | after_affected, db_session)

    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
        shown_version_id=shown_version_id,
    )


@user_router.get("/custom/{skill_id}/share")
def fetch_custom_skill_sharing(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_editable_skill(
        skill_id, user=user, db_session=db_session, any_plugin=True
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
    skill = fetch_editable_skill(
        skill_id,
        user=user,
        db_session=db_session,
        lock_for_update=True,
        any_plugin=True,
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
    push_skills_and_commit(affected, db_session)
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
    visible = fetch_skill(skill_id, user=user, db_session=db_session)
    if visible is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if isinstance(visible, Skill):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{visible.name}' is a built-in and cannot change ownership.",
        )
    skill = lock_plugin(visible.id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    author = (
        fetch_user_by_id(db_session, skill.author_user_id)
        if skill.author_user_id is not None
        else None
    )
    ownership_vacant = author is None or not author.is_active
    if skill.author_user_id != user.id and not (
        has_global_permission(user, Permission.MANAGE_PLUGINS) and ownership_vacant
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only the owner can transfer ownership of this skill.",
        )

    target = fetch_new_skill_owner(transfer_req.new_owner_user_id, db_session)
    if target.id == skill.author_user_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This user already owns the skill.",
        )
    # The previous owner keeps an EDITOR share, which Sharing off forbids.
    if not has_global_permission(user, Permission.MANAGE_PLUGINS):
        check_sharing_allowed()

    before_affected = affected_user_ids_for_plugins([skill.id], db_session)
    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=target.id,
        db_session=db_session,
    )

    after_affected = affected_user_ids_for_plugins([skill.id], db_session)
    db_session.commit()
    db_session.expire(skill)
    push_skills_and_commit(before_affected | after_affected, db_session)
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
    skill = fetch_editable_skill(
        skill_id,
        user=user,
        db_session=db_session,
        lock_for_update=True,
        any_plugin=True,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected, file_ids = delete_skill_for_user__no_commit(skill, user, db_session)
    db_session.commit()

    push_skills_and_commit(affected, db_session)
    delete_files_best_effort(file_ids, context=_BUNDLE_CLEANUP)
