"""Push skill bundles to running sandboxes."""

import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import (
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.models import Skill, User
from onyx.db.skill import (
    RuntimeSkill,
    SkillValidityUpdate,
    affected_user_ids_for_skill,
    list_runtime_skills_for_user,
    persist_skill_validity,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import ENABLE_CRAFT
from onyx.server.features.build.db.sandbox import (
    get_sandbox_user_map,
    lock_sandbox_skills_hashes,
    set_sandbox_skills_hashes__no_commit,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.image.sandbox_daemon.extract import (
    MAX_BUNDLE_BYTES,
    MAX_FILE_BYTES,
)
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from onyx.server.features.build.timeouts import QUEUE_RESIDENCY_SECONDS
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    COMPANY_SEARCH,
    EXTERNAL_APP_SKILL_ID_TO_APP_TYPE,
    BuiltInSkillDefinition,
)
from onyx.skills.bundle import (
    DEFAULT_PER_FILE_MAX_BYTES,
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    open_bundle_zip,
)
from onyx.skills.content import iter_builtin_skill_files
from onyx.skills.rendering import (
    CLAUDE_SKILL_DIR_PLACEHOLDER,
    render_company_search_skill,
    render_external_app_files,
    resolve_skill_dir_placeholder,
)
from onyx.skills.validation import (
    load_stored_custom_skill_bundle,
    validate_stored_custom_skill,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

SKILLS_MOUNT_PATH = "/workspace/managed/skills"


def compute_skill_runtime_hash(
    files: FileSet,
    connectable_apps_section: str,
) -> str:
    """Digest the skill files and the app guidance rendered into ``AGENTS.md``.
    A change makes a live session stale so it hot-reloads. The craft MCP set is
    tracked separately via ``mcp_config_hash`` (see ``session_runtime_stale``)."""
    digest = hashlib.sha256()
    connectable_apps_bytes = connectable_apps_section.encode()
    digest.update(len(connectable_apps_bytes).to_bytes(8))
    digest.update(connectable_apps_bytes)
    for path in sorted(files):
        path_bytes = path.encode()
        content = files[path]
        digest.update(len(path_bytes).to_bytes(8))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8))
        digest.update(content)
    return digest.hexdigest()


def _add_static_builtin(
    files: FileSet, skill: Skill, definition: BuiltInSkillDefinition
) -> None:
    source_dir = definition.source_dir
    for path in iter_builtin_skill_files(source_dir):
        # Template sources are rendered separately; never ship them raw.
        if path.suffix == TEMPLATE_SUFFIX:
            continue
        rel = path.relative_to(source_dir)
        files[f"{skill.name}/{rel.as_posix()}"] = path.read_bytes()


def _render_template(
    files: FileSet,
    skill: Skill,
    definition: BuiltInSkillDefinition,
    db_session: Session,
    user: User,
) -> None:
    """Overwrite ``{name}/SKILL.md`` with a per-user rendering. company-search
    and external-app built-ins have renderers; any other templated built-in logs
    a warning and ships the static siblings as-is."""
    if definition.built_in_skill_id == COMPANY_SEARCH.built_in_skill_id:
        rendered = render_company_search_skill(
            db_session, user, definition.source_dir.parent
        )
        files[f"{skill.name}/SKILL.md"] = rendered.encode("utf-8")
        return

    app_type = EXTERNAL_APP_SKILL_ID_TO_APP_TYPE.get(definition.built_in_skill_id)
    if app_type is not None:
        rendered = render_external_app_files(
            db_session, skill, app_type, definition.source_dir
        )
        for name, content in rendered.items():
            files[f"{skill.name}/{name}"] = content.encode("utf-8")
        return

    logger.warning(
        "Built-in %s has_template=True but no renderer", definition.built_in_skill_id
    )


def _resolved_size(name: str, skill_md: bytes) -> int:
    """Size of a root ``SKILL.md`` after ``${CLAUDE_SKILL_DIR}`` resolution."""
    placeholder = CLAUDE_SKILL_DIR_PLACEHOLDER.encode()
    return len(skill_md) + skill_md.count(placeholder) * (
        len(f"{SKILLS_MOUNT_PATH}/{name}".encode()) - len(placeholder)
    )


def _add_bundle_bytes(
    files: FileSet, name: str, bundle_file_id: str | None, bundle_bytes: bytes
) -> None:
    try:
        bundle_files: FileSet = {}
        with open_bundle_zip(bundle_bytes) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            # A member never reads past its declared size, so this bounds memory
            # before the receiver would refuse the whole push.
            total = sum(len(content) for content in files.values()) + sum(
                info.file_size for info in infos
            )
            if total > MAX_BUNDLE_BYTES:
                logger.warning(
                    "Skipping skill %s: the skills exceed the sandbox size limit",
                    name,
                )
                return
            for info in infos:
                bundle_files[f"{name}/{info.filename}"] = zf.read(info)
        skill_md = bundle_files.get(f"{name}/{SKILL_MD_NAME}", b"")
        resolved = _resolved_size(name, skill_md)
        # Count the resolved instructions now, so a Skill that resolution would
        # drop does not push later Skills over the total.
        if (
            resolved > min(DEFAULT_PER_FILE_MAX_BYTES, MAX_FILE_BYTES)
            or total - len(skill_md) + resolved > MAX_BUNDLE_BYTES
        ):
            logger.warning(
                "Skipping skill %s: resolved instructions exceed a sandbox size limit",
                name,
            )
            return
        files.update(bundle_files)
    except Exception:
        logger.warning(
            "Failed to unpack bundle for skill %s (%s), skipping",
            name,
            bundle_file_id,
            exc_info=True,
        )


def _resolve_skill_dirs(files: FileSet, skill_names: Iterable[str]) -> None:
    """Point ``${CLAUDE_SKILL_DIR}`` in each root ``SKILL.md`` at the skill's
    sandbox folder. Only the sent copy changes, not the stored bundle."""
    placeholder = CLAUDE_SKILL_DIR_PLACEHOLDER.encode()
    total = sum(len(content) for content in files.values())
    file_limit = min(DEFAULT_PER_FILE_MAX_BYTES, MAX_FILE_BYTES)
    for name in skill_names:
        path = f"{name}/{SKILL_MD_NAME}"
        content = files.get(path)
        if content is None or placeholder not in content:
            continue
        skill_dir = f"{SKILLS_MOUNT_PATH}/{name}"
        resolved_size = _resolved_size(name, content)
        resolved_total = total - len(content) + resolved_size
        if resolved_size > file_limit or resolved_total > MAX_BUNDLE_BYTES:
            logger.warning(
                "Skipping skill %s: resolved instructions exceed a sandbox size limit",
                name,
            )
            prefix = f"{name}/"
            for skill_path in [key for key in files if key.startswith(prefix)]:
                total -= len(files.pop(skill_path))
            continue
        total = resolved_total
        files[path] = resolve_skill_dir_placeholder(
            content.decode("utf-8"), skill_dir
        ).encode("utf-8")


def _assemble(
    skills: Iterable[RuntimeSkill],
    user: User,
    db_session: Session,
) -> tuple[FileSet, set[UUID]]:
    """Return the hydrated skills as a flat ``{path: bytes}`` map, and the
    skills whose version lazy validation found invalid.

    Built-ins render from disk. A custom skill sends the bundle of the plugin
    version the user runs, in a folder named by that version's frontmatter.
    The version must already be valid or pass lazy validation before its
    FileStore bundle is unpacked. Invalid, indeterminate, and unknown built-in
    rows are skipped.
    """

    files: FileSet = {}
    seen_names: set[str] = set()
    validity_updates: list[SkillValidityUpdate] = []
    file_store = get_default_file_store()

    for runtime_skill in skills:
        skill = runtime_skill.skill
        name = runtime_skill.name
        if name in seen_names:
            logger.warning(
                "Skipping skill %s: another skill is named '%s'", skill.id, name
            )
            continue
        seen_names.add(name)
        if skill.built_in_skill_id is None:
            version = runtime_skill.version
            if version is None or version.is_valid is False:
                continue

            if version.is_valid is None:
                validation = validate_stored_custom_skill(
                    runtime_skill.name, version.bundle_file_id, file_store
                )
                if validation.is_valid is not None:
                    validity_updates.append(
                        SkillValidityUpdate(
                            skill_id=skill.id,
                            bundle_file_id=version.bundle_file_id,
                            is_valid=validation.is_valid,
                        )
                    )
                if validation.normalized_bundle is None:
                    logger.warning(
                        "Skipping unvalidated skill %s: %s",
                        skill.id,
                        validation.detail,
                    )
                    continue
                bundle_bytes = validation.normalized_bundle
            else:
                try:
                    if version.bundle_file_id is None:
                        continue
                    bundle_bytes = load_stored_custom_skill_bundle(
                        version.bundle_file_id,
                        file_store,
                    ).content
                except Exception as exc:
                    logger.warning(
                        "Skipping unreadable valid skill %s: %s",
                        skill.id,
                        exc,
                    )
                    continue

            _add_bundle_bytes(
                files, runtime_skill.name, version.bundle_file_id, bundle_bytes
            )
            continue
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            logger.warning(
                "Skill row %s references unknown built-in %s; skipping",
                skill.name,
                skill.built_in_skill_id,
            )
            continue
        _add_static_builtin(files, skill, definition)
        if definition.has_template:
            _render_template(files, skill, definition, db_session, user)

    _resolve_skill_dirs(files, sorted(seen_names))

    try:
        persist_skill_validity(validity_updates)
    except Exception:
        logger.exception("Failed to persist skill validity classifications")
    return files, {
        update.skill_id for update in validity_updates if update.is_valid is False
    }


def _assemble_fileset(
    skills: Iterable[RuntimeSkill],
    user: User,
    db_session: Session,
) -> FileSet:
    return _assemble(skills, user, db_session)[0]


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return a flat ``{path: bytes}`` map of every skill the user can see.

    An unvalidated version can keep a skill name and hide a valid skill with
    that name. When it fails validation, the next pass leaves it out of the
    name order, so the name goes to the next skill. A pass runs again only
    when it finds a new invalid version, so the passes end.
    """
    invalid: set[UUID] = set()
    while True:
        skills = list_runtime_skills_for_user(
            user=user, db_session=db_session, left_out=invalid
        )
        files, found_invalid = _assemble(skills, user, db_session)
        if found_invalid <= invalid:
            return files
        invalid |= found_invalid


def build_user_skills_payload(user: User, db_session: Session) -> tuple[str, FileSet]:
    """Return the connectable-apps section and skill fileset.

    The connectable-apps section lists org apps the user has not connected yet,
    so the agent can offer to set one up through the connect tool.
    """
    files = build_skills_fileset_for_user(user, db_session)
    connectable_apps_section = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    return connectable_apps_section, files


def push_skill_to_affected_sandboxes(skill: Skill, db_session: Session) -> None:
    """Resolve affected users for *skill* and push updated filesets."""
    user_ids = affected_user_ids_for_skill(skill, db_session)
    push_skills_for_users(user_ids, db_session)


def push_skills_for_users(user_ids: set[UUID], db_session: Session) -> None:
    """Push skill state changes and mark affected sessions for reload."""
    if not user_ids:
        return
    try:
        sandbox_map = get_sandbox_user_map(list(user_ids), db_session)
        current_hashes = lock_sandbox_skills_hashes(db_session, set(sandbox_map))
        sandbox_payloads = {
            sandbox_id: build_user_skills_payload(user, db_session)
            for sandbox_id, user in sandbox_map.items()
        }
        desired_hashes = {
            sandbox_id: compute_skill_runtime_hash(files, connectable_apps_section)
            for sandbox_id, (
                connectable_apps_section,
                files,
            ) in sandbox_payloads.items()
        }
        changed_files = {
            sandbox_id: files
            for sandbox_id, (
                _connectable_apps_section,
                files,
            ) in sandbox_payloads.items()
            if current_hashes.get(sandbox_id) != desired_hashes[sandbox_id]
        }
        if not changed_files:
            return
        result = get_sandbox_manager().push_to_sandboxes(
            mount_path=SKILLS_MOUNT_PATH,
            sandbox_files=changed_files,
        )
        failed_sandbox_ids = {failure.sandbox_id for failure in result.failures}
        for failure in result.failures:
            logger.warning(
                "Skill push failed for sandbox %s: %s: %s",
                failure.sandbox_id,
                failure.reason,
                failure.detail,
            )
        successful_sandbox_ids = set(changed_files) - failed_sandbox_ids
        if not successful_sandbox_ids:
            return
        try:
            with db_session.begin_nested():
                set_sandbox_skills_hashes__no_commit(
                    db_session,
                    {
                        sandbox_id: desired_hashes[sandbox_id]
                        for sandbox_id in successful_sandbox_ids
                    },
                )
        except Exception:
            logger.exception("Failed to persist successful skill push state")
    except Exception:
        logger.exception("Failed to push skills to sandboxes")


def enqueue_skill_push(user_ids: Iterable[UUID]) -> None:
    """Push to the users in the background, after the caller committed. For a
    change that can reach many users, such as a group membership sync, so the
    request does not wait for the pushes."""
    from onyx.background.celery.versioned_apps.client import app as celery_app

    ids = sorted({str(user_id) for user_id in user_ids})
    # No Craft, no sandboxes; Lite also runs no Celery workers.
    if not ids or not ENABLE_CRAFT:
        return
    celery_app.send_task(
        OnyxCeleryTask.PUSH_SKILLS_TO_USERS,
        kwargs={"user_ids": ids, "tenant_id": get_current_tenant_id()},
        queue=OnyxCeleryQueues.SANDBOX,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=QUEUE_RESIDENCY_SECONDS,
    )


def push_skills_and_commit(user_ids: Iterable[UUID], db_session: Session) -> None:
    """Push to the users after the caller committed the change, and commit the
    push state."""
    push_skills_for_users(set(user_ids), db_session)
    try:
        db_session.commit()
    except Exception:
        # The caller's change is already committed; a lost push state only
        # makes the next push send the skills again.
        db_session.rollback()
        logger.exception("Failed to commit the skill push state")
