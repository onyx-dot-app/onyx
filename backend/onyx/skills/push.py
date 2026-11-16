"""Push skill bundles to running sandboxes."""

import hashlib
from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
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
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.build.configs import ENABLE_CRAFT
from onyx.server.features.build.db.sandbox import (
    get_sandbox_user_map,
    lock_sandbox_skills_states,
    set_sandbox_skills_states__no_commit,
)
from onyx.server.features.build.sandbox.base import PUSH_PARALLELISM
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
)
from onyx.skills.models import SandboxSkillsState, SkillOmission, SkillUsage
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


class AssembledSkills(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: FileSet
    omissions: tuple[SkillOmission, ...]
    # Plugins whose version lazy validation found invalid.
    found_invalid: frozenset[UUID] = frozenset()


class UserSkillsPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    connectable_apps_section: str
    files: FileSet
    # Plugins the run-time skill limit left out of ``files``.
    omissions: tuple[SkillOmission, ...]

    @property
    def state(self) -> SandboxSkillsState:
        """What a sandbox that gets this payload records."""
        return SandboxSkillsState(
            skills_hash=compute_skill_runtime_hash(
                self.files, self.connectable_apps_section
            ),
            omissions=self.omissions,
        )


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
    ``${CLAUDE_SKILL_DIR}`` resolved). The recorded size decides before the
    bundle is read. A skill that would pass the transport cap
    (``MAX_BUNDLE_BYTES``) is skipped.
    """
    files: FileSet = {}
    omissions: list[SkillOmission] = []
    used = SkillUsage()
    sent = 0
    seen_names: set[str] = set()
    validity_updates: list[SkillValidityUpdate] = []
    file_store = get_default_file_store()

    def left_out(runtime_skill: RuntimeSkill, usage: SkillUsage) -> bool:
        total = used + usage
        reason: Literal["bytes", "files"]
        if total.bytes > SKILL_RUNTIME_MAX_BYTES:
            reason = "bytes"
        elif total.files > SKILL_RUNTIME_MAX_FILES:
            reason = "files"
        else:
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
                with open_bundle_zip(bundle_bytes) as zf:
                    infos = [info for info in zf.infolist() if not info.is_dir()]
                    # The zip directory bounds memory before the files are read.
                    size = _larger(
                        runtime_skill.usage,
                        SkillUsage(
                            bytes=sum(info.file_size for info in infos),
                            files=len(infos),
                        ),
                    )
                    if left_out(runtime_skill, size):
                        continue
                    skill_files = {
                        f"{name}/{info.filename}": zf.read(info) for info in infos
                    }
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
        sent_size = _usage_of(skill_files).bytes
        if sent + sent_size > MAX_BUNDLE_BYTES:
            logger.warning(
                "Skipping skill %s: the skills exceed the sandbox size limit", name
            )
            continue
        files.update(skill_files)
        seen_names.add(name)
        used += size
        sent += sent_size

    try:
        persist_skill_validity(validity_updates)
    except Exception:
        logger.exception("Failed to persist skill validity classifications")
    return AssembledSkills(
        files=files,
        omissions=tuple(omissions),
        found_invalid=frozenset(
            update.skill_id for update in validity_updates if update.is_valid is False
        ),
    )


def _assemble_fileset(
    skills: Iterable[RuntimeSkill],
    user: User,
    db_session: Session,
) -> FileSet:
    return _assemble_skills(skills, user, db_session).files


def build_user_skills_payload(user: User, db_session: Session) -> UserSkillsPayload:
    """Return the connectable-apps section and the skill files within the
    run-time skill limit, with the plugins it left out.

    The connectable-apps section lists org apps the user has not connected yet,
    so the agent can offer to set one up through the connect tool.

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
        assembled = _assemble_skills(skills, user, db_session)
        if assembled.found_invalid <= invalid:
            break
        invalid |= assembled.found_invalid
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


def push_skills_for_users(user_ids: set[UUID], db_session: Session) -> None:
    """Push skill state changes and mark affected sessions for reload. Builds
    payloads one at a time and sends them in parallel batches. A batch is sent
    when it holds ``PUSH_PARALLELISM`` sandboxes or one run-time limit of files,
    so a few large payloads do not all stay in memory."""
    if not user_ids:
        return
    try:
        sandbox_map = get_sandbox_user_map(list(user_ids), db_session)
        current_states = lock_sandbox_skills_states(db_session, set(sandbox_map))
    except Exception:
        logger.exception("Failed to push skills to sandboxes")
        return
    delivered: dict[UUID, SandboxSkillsState] = {}
    batch_files: dict[UUID, FileSet] = {}
    batch_states: dict[UUID, SandboxSkillsState] = {}
    batch_bytes = 0

    def send_batch() -> None:
        nonlocal batch_bytes
        if not batch_files:
            return
        try:
            result = get_sandbox_manager().push_to_sandboxes(
                mount_path=SKILLS_MOUNT_PATH, sandbox_files=batch_files
            )
            failed_ids = {failure.sandbox_id for failure in result.failures}
            for failure in result.failures:
                logger.warning(
                    "Skill push failed for sandbox %s: %s: %s",
                    failure.sandbox_id,
                    failure.reason,
                    failure.detail,
                )
        except Exception:
            logger.exception("Failed to push skills to sandboxes")
            failed_ids = set(batch_files)
        for sandbox_id in batch_files.keys() - failed_ids:
            delivered[sandbox_id] = batch_states[sandbox_id]
        batch_files.clear()
        batch_states.clear()
        batch_bytes = 0

    for sandbox_id in sorted(sandbox_map):
        try:
            payload = build_user_skills_payload(sandbox_map[sandbox_id], db_session)
        except Exception:
            logger.exception("Failed to build skills for sandbox %s", sandbox_id)
            continue
        state = payload.state
        current = current_states.get(sandbox_id)
        if current is not None and current.skills_hash == state.skills_hash:
            if current.omissions != state.omissions:
                delivered[sandbox_id] = state
            continue
        batch_files[sandbox_id] = payload.files
        batch_states[sandbox_id] = state
        batch_bytes += sum(len(content) for content in payload.files.values())
        if (
            len(batch_files) >= PUSH_PARALLELISM
            or batch_bytes >= SKILL_RUNTIME_MAX_BYTES
        ):
            send_batch()
    send_batch()
    if not delivered:
        return
    try:
        with db_session.begin_nested():
            set_sandbox_skills_states__no_commit(db_session, delivered)
    except Exception:
        logger.exception("Failed to persist successful skill push state")


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
