"""Push skill bundles to running sandboxes."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.models import Skill, User
from onyx.db.skill import (
    RuntimeSkill,
    SkillValidityUpdate,
    affected_user_ids_for_skill,
    list_runtime_skills_for_user,
    persist_skill_validity,
)
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.build.db.sandbox import (
    SandboxSkillsState,
    get_sandbox_user_map,
    lock_sandbox_skills_states,
    set_sandbox_skills_states__no_commit,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.image.sandbox_daemon.extract import (
    MAX_FILE_BYTES,
)
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    COMPANY_SEARCH,
    EXTERNAL_APP_SKILL_ID_TO_APP_TYPE,
    BuiltInSkillDefinition,
    iter_builtin_skill_files,
)
from onyx.skills.bundle import (
    DEFAULT_PER_FILE_MAX_BYTES,
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    open_bundle_zip,
)
from onyx.skills.limits import (
    SKILL_RUNTIME_MAX_BYTES,
    SKILL_RUNTIME_MAX_FILES,
    SkillOmission,
    SkillUsage,
)
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


def _omission_reason(
    used: SkillUsage, usage: SkillUsage
) -> Literal["bytes", "files"] | None:
    """Why ``usage`` does not fit the run-time limit next to ``used``, or None
    when it fits. The byte limit is also the transport cap of a push."""
    total = used + usage
    if total.bytes > SKILL_RUNTIME_MAX_BYTES:
        return "bytes"
    if total.files > SKILL_RUNTIME_MAX_FILES:
        return "files"
    return None


def _larger(first: SkillUsage | None, second: SkillUsage) -> SkillUsage:
    if first is None:
        return second
    return SkillUsage(
        bytes=max(first.bytes, second.bytes), files=max(first.files, second.files)
    )


def _usage_of(files: FileSet) -> SkillUsage:
    return SkillUsage(
        bytes=sum(len(content) for content in files.values()), files=len(files)
    )


def _resolve_skill_dir(files: FileSet, name: str) -> bool:
    """Point ``${CLAUDE_SKILL_DIR}`` in the root ``SKILL.md`` of one skill's
    files at the skill's sandbox folder. Only the sent copy changes, not the
    stored bundle. False when the resolved file passes the per-file limit."""
    path = f"{name}/{SKILL_MD_NAME}"
    content = files.get(path)
    if content is None or CLAUDE_SKILL_DIR_PLACEHOLDER.encode() not in content:
        return True
    resolved = resolve_skill_dir_placeholder(
        content.decode("utf-8"), f"{SKILLS_MOUNT_PATH}/{name}"
    ).encode("utf-8")
    if len(resolved) > min(DEFAULT_PER_FILE_MAX_BYTES, MAX_FILE_BYTES):
        logger.warning(
            "Skipping skill %s: resolved instructions exceed the file size limit",
            name,
        )
        return False
    files[path] = resolved
    return True


def _bundle_usage(bundle_bytes: bytes) -> SkillUsage:
    """Size and file count of a bundle's files, from the zip directory."""
    with open_bundle_zip(bundle_bytes) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
    return SkillUsage(bytes=sum(info.file_size for info in infos), files=len(infos))


def _unpack_bundle(name: str, bundle_bytes: bytes) -> FileSet:
    with open_bundle_zip(bundle_bytes) as zf:
        return {
            f"{name}/{info.filename}": zf.read(info)
            for info in zf.infolist()
            if not info.is_dir()
        }


def _load_custom_bundle(
    runtime_skill: RuntimeSkill,
    file_store: FileStore,
    validity_updates: list[SkillValidityUpdate],
) -> bytes | None:
    """The bundle of the plugin version the user runs, or None when it is
    invalid, fails lazy validation or cannot be read."""
    skill = runtime_skill.skill
    version = runtime_skill.version
    if version is None or version.is_valid is False:
        return None
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
                "Skipping unvalidated skill %s: %s", skill.id, validation.detail
            )
        return validation.normalized_bundle
    if version.bundle_file_id is None:
        return None
    try:
        return load_stored_custom_skill_bundle(
            version.bundle_file_id, file_store
        ).content
    except Exception as exc:
        logger.warning("Skipping unreadable valid skill %s: %s", skill.id, exc)
        return None


@dataclass(frozen=True)
class AssembledSkills:
    files: FileSet
    omissions: tuple[SkillOmission, ...]


def _assemble_skills(
    skills: Iterable[RuntimeSkill], user: User, db_session: Session
) -> AssembledSkills:
    """Hydrate the skills, in the keep order, as a flat ``{path: bytes}`` map.

    Built-ins render from disk. A custom skill sends the bundle of the plugin
    version the user runs, in a folder named by that version's frontmatter.
    The version must already be valid or pass lazy validation before its
    FileStore bundle is unpacked. Invalid, indeterminate, and unknown built-in
    rows are skipped.

    The run-time limit applies to one running total: a skill that does not
    fit is left out, and later ones still load if they fit. A custom skill
    counts its recorded size, or the files sent when they are larger (with
    ``${CLAUDE_SKILL_DIR}`` resolved), so the total also keeps the push within
    the transport cap. The recorded size decides before the bundle is read.
    """
    files: FileSet = {}
    omissions: list[SkillOmission] = []
    used = SkillUsage()
    seen_names: set[str] = set()
    validity_updates: list[SkillValidityUpdate] = []
    file_store = get_default_file_store()

    def left_out(runtime_skill: RuntimeSkill, usage: SkillUsage) -> bool:
        reason = _omission_reason(used, usage)
        if reason is None:
            return False
        logger.info(
            "Skill %s did not fit the run-time skill limit (%s)",
            runtime_skill.skill.id,
            reason,
        )
        omissions.append(
            SkillOmission(
                plugin_id=runtime_skill.skill.id,
                name=runtime_skill.name,
                bytes=usage.bytes,
                files=usage.files,
                reason=reason,
            )
        )
        return True

    for runtime_skill in skills:
        skill = runtime_skill.skill
        name = runtime_skill.name
        if name in seen_names:
            logger.warning(
                "Skipping skill %s: another skill is named '%s'", skill.id, name
            )
            continue
        skill_files: FileSet = {}
        size = SkillUsage()
        if skill.built_in_skill_id is None:
            if runtime_skill.usage is not None and left_out(
                runtime_skill, runtime_skill.usage
            ):
                continue
            bundle_bytes = _load_custom_bundle(
                runtime_skill, file_store, validity_updates
            )
            if bundle_bytes is None:
                continue
            try:
                # The zip directory bounds memory before the files are read.
                size = _larger(runtime_skill.usage, _bundle_usage(bundle_bytes))
                if left_out(runtime_skill, size):
                    continue
                skill_files = _unpack_bundle(name, bundle_bytes)
            except Exception:
                logger.warning(
                    "Failed to unpack bundle for skill %s, skipping",
                    skill.id,
                    exc_info=True,
                )
                continue
        else:
            definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
            if definition is None:
                logger.warning(
                    "Skill row %s references unknown built-in %s; skipping",
                    skill.name,
                    skill.built_in_skill_id,
                )
                continue
            _add_static_builtin(skill_files, skill, definition)
            if definition.has_template:
                _render_template(skill_files, skill, definition, db_session, user)
        if not _resolve_skill_dir(skill_files, name):
            continue
        size = _larger(size, _usage_of(skill_files))
        if left_out(runtime_skill, size):
            continue
        files.update(skill_files)
        seen_names.add(name)
        used += size

    try:
        persist_skill_validity(validity_updates)
    except Exception:
        logger.exception("Failed to persist skill validity classifications")
    return AssembledSkills(files=files, omissions=tuple(omissions))


def _assemble_fileset(
    skills: Iterable[RuntimeSkill],
    user: User,
    db_session: Session,
) -> FileSet:
    return _assemble_skills(skills, user, db_session).files


@dataclass(frozen=True)
class UserSkillsPayload:
    connectable_apps_section: str
    files: FileSet
    # Plugins the run-time skill limit left out of ``files``.
    omissions: tuple[SkillOmission, ...]


def build_user_skills_payload(user: User, db_session: Session) -> UserSkillsPayload:
    """Return the connectable-apps section and the skill files within the
    run-time skill limit, with the plugins it left out.

    The connectable-apps section lists org apps the user has not connected yet,
    so the agent can offer to set one up through the connect tool.
    """
    skills = list_runtime_skills_for_user(user=user, db_session=db_session)
    assembled = _assemble_skills(skills, user, db_session)
    connectable_apps_section = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    return UserSkillsPayload(
        connectable_apps_section=connectable_apps_section,
        files=assembled.files,
        omissions=assembled.omissions,
    )


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return the skill files a sandbox of the user gets."""
    return build_user_skills_payload(user, db_session).files


def push_skill_to_affected_sandboxes(skill: Skill, db_session: Session) -> None:
    """Resolve affected users for *skill* and push updated filesets."""
    user_ids = affected_user_ids_for_skill(skill, db_session)
    push_skills_for_users(user_ids, db_session)


@dataclass(frozen=True)
class _SandboxPush:
    # The state to record; None when nothing changed or the send failed.
    state: SandboxSkillsState | None
    sent: bool
    failed: bool


def _push_one_sandbox(
    sandbox_id: UUID,
    user: User,
    current: SandboxSkillsState | None,
    db_session: Session,
) -> _SandboxPush:
    """Build one sandbox's payload and send it when its hash changed."""
    payload = build_user_skills_payload(user, db_session)
    state = SandboxSkillsState(
        skills_hash=compute_skill_runtime_hash(
            payload.files, payload.connectable_apps_section
        ),
        omissions=payload.omissions,
    )
    if current is not None and current.skills_hash == state.skills_hash:
        changed = current.omissions != state.omissions
        return _SandboxPush(state=state if changed else None, sent=False, failed=False)
    result = get_sandbox_manager().push_to_sandbox(
        sandbox_id=sandbox_id, mount_path=SKILLS_MOUNT_PATH, files=payload.files
    )
    for failure in result.failures:
        logger.warning(
            "Skill push failed for sandbox %s: %s: %s",
            failure.sandbox_id,
            failure.reason,
            failure.detail,
        )
    failed = result.succeeded != result.targets
    return _SandboxPush(state=None if failed else state, sent=True, failed=failed)


def push_skills_for_users(user_ids: set[UUID], db_session: Session) -> None:
    """Push skill state changes and mark affected sessions for reload. Builds
    and sends one sandbox at a time, so only one payload is in memory."""
    if not user_ids:
        return
    try:
        sandbox_map = get_sandbox_user_map(list(user_ids), db_session)
        current_states = lock_sandbox_skills_states(db_session, set(sandbox_map))
    except Exception:
        logger.exception("Failed to push skills to sandboxes")
        return
    delivered: dict[UUID, SandboxSkillsState] = {}
    sent = failed = 0
    for sandbox_id in sorted(sandbox_map):
        try:
            outcome = _push_one_sandbox(
                sandbox_id,
                sandbox_map[sandbox_id],
                current_states.get(sandbox_id),
                db_session,
            )
        except Exception:
            logger.exception("Failed to push skills to sandbox %s", sandbox_id)
            continue
        sent += outcome.sent
        failed += outcome.failed
        if outcome.state is not None:
            delivered[sandbox_id] = outcome.state
    if failed:
        logger.warning("Skill push: %d/%d targets failed", failed, sent)
    if not delivered:
        return
    try:
        with db_session.begin_nested():
            set_sandbox_skills_states__no_commit(db_session, delivered)
    except Exception:
        logger.exception("Failed to persist successful skill push state")


def push_skills_and_commit(user_ids: Iterable[UUID], db_session: Session) -> None:
    """Push to the users after the caller committed the change, and commit the
    push state."""
    push_skills_for_users(set(user_ids), db_session)
    db_session.commit()
