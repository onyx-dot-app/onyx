"""Push skill bundles to running sandboxes."""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.models import Skill, User
from onyx.db.plugin_access import RuntimePluginCharge, runtime_plugin_charges
from onyx.db.skill import (
    RuntimeSkill,
    SkillValidityUpdate,
    affected_user_ids_for_skill,
    keep_one_skill_per_name,
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
    BUILT_IN_SKILL_RUNTIME_USAGE,
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
    KeepGroup,
    SkillOmission,
    SkillUsage,
    charged_file_bytes,
    runtime_keep_key,
    runtime_omission_reason,
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


def _resolved_size(name: str, skill_md: bytes) -> int:
    """Size of a root ``SKILL.md`` after ``${CLAUDE_SKILL_DIR}`` resolution."""
    placeholder = CLAUDE_SKILL_DIR_PLACEHOLDER.encode()
    return len(skill_md) + skill_md.count(placeholder) * (
        len(f"{SKILLS_MOUNT_PATH}/{name}".encode()) - len(placeholder)
    )


def _sent_bytes(files: FileSet) -> int:
    """Bytes the sandbox receives for ``files``, with each root ``SKILL.md``
    at its size after ``${CLAUDE_SKILL_DIR}`` resolution."""
    total = 0
    for path, content in files.items():
        name, _, rest = path.partition("/")
        total += (
            _resolved_size(name, content) if rest == SKILL_MD_NAME else len(content)
        )
    return total


class _BundleAdd(Enum):
    ADDED = "added"
    # The push would pass the transport cap; the run-time limit records it.
    TOO_LARGE = "too_large"
    SKIPPED = "skipped"


def _add_bundle_bytes(
    files: FileSet, name: str, bundle_file_id: str | None, bundle_bytes: bytes
) -> _BundleAdd:
    """Add a bundle's files under ``name`` if the push stays within the
    transport cap ``SKILL_RUNTIME_MAX_BYTES``."""
    try:
        bundle_files: FileSet = {}
        with open_bundle_zip(bundle_bytes) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            # A member never reads past its declared size, so this bounds memory
            # before the receiver would refuse the whole push.
            total = _sent_bytes(files) + sum(info.file_size for info in infos)
            if total > SKILL_RUNTIME_MAX_BYTES:
                logger.warning(
                    "Skipping skill %s: the skills exceed the sandbox size limit",
                    name,
                )
                return _BundleAdd.TOO_LARGE
            for info in infos:
                bundle_files[f"{name}/{info.filename}"] = zf.read(info)
        skill_md = bundle_files.get(f"{name}/{SKILL_MD_NAME}", b"")
        resolved = _resolved_size(name, skill_md)
        # Count the resolved instructions now, so a Skill that resolution would
        # drop does not push later Skills over the total.
        if resolved > min(DEFAULT_PER_FILE_MAX_BYTES, MAX_FILE_BYTES):
            logger.warning(
                "Skipping skill %s: resolved instructions exceed the file size limit",
                name,
            )
            return _BundleAdd.SKIPPED
        if total - len(skill_md) + resolved > SKILL_RUNTIME_MAX_BYTES:
            logger.warning(
                "Skipping skill %s: resolved instructions exceed the sandbox size limit",
                name,
            )
            return _BundleAdd.TOO_LARGE
        files.update(bundle_files)
        return _BundleAdd.ADDED
    except Exception:
        logger.warning(
            "Failed to unpack bundle for skill %s (%s), skipping",
            name,
            bundle_file_id,
            exc_info=True,
        )
        return _BundleAdd.SKIPPED


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
        if resolved_size > file_limit or resolved_total > SKILL_RUNTIME_MAX_BYTES:
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


def _bundle_runtime_usage(bundle_bytes: bytes) -> SkillUsage | None:
    """Charged usage of a bundle's files, each at least 4 KB."""
    try:
        with open_bundle_zip(bundle_bytes) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
    except Exception:
        return None
    return SkillUsage(
        bytes=sum(charged_file_bytes(info.file_size) for info in infos),
        files=len(infos),
    )


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


def _runtime_keep_key(
    runtime_skill: RuntimeSkill, charges: Mapping[UUID, RuntimePluginCharge]
) -> tuple[int, float, UUID]:
    skill_id = runtime_skill.skill.id
    if runtime_skill.skill.built_in_skill_id is not None:
        return runtime_keep_key(KeepGroup.BUILT_IN, None, skill_id)
    charge = charges.get(skill_id)
    if charge is None:
        return runtime_keep_key(KeepGroup.INSTALLED_BY_DEFAULT, None, skill_id)
    return runtime_keep_key(charge.group, charge.order_time, skill_id)


@dataclass(frozen=True)
class AssembledSkills:
    files: FileSet
    omissions: tuple[SkillOmission, ...]


def _assemble_skills(
    skills: Iterable[RuntimeSkill],
    user: User,
    db_session: Session,
    charges: Mapping[UUID, RuntimePluginCharge] | None,
) -> AssembledSkills:
    """Hydrate the skills as a flat ``{path: bytes}`` map.

    Built-ins render from disk. A custom skill sends the bundle of the plugin
    version the user runs, in a folder named by that version's frontmatter.
    The version must already be valid or pass lazy validation before its
    FileStore bundle is unpacked. Invalid, indeterminate, and unknown built-in
    rows are skipped. Of two skills with one name, the name order keeps one.

    With ``charges``, the run-time limit applies: skills load in the keep
    order while they fit, and whole plugins that do not fit are left out. A
    version with no recorded size is measured from its bundle.
    """
    skills, hidden = keep_one_skill_per_name(skills)
    for runtime_skill in hidden:
        logger.warning(
            "Skipping skill %s: another skill is named '%s'",
            runtime_skill.skill.id,
            runtime_skill.name,
        )
    seen_names = {runtime_skill.name for runtime_skill in skills}
    if charges is not None:
        skills = sorted(skills, key=lambda item: _runtime_keep_key(item, charges))

    files: FileSet = {}
    omissions: list[SkillOmission] = []
    used = SkillUsage()
    validity_updates: list[SkillValidityUpdate] = []
    file_store = get_default_file_store()

    def left_out(runtime_skill: RuntimeSkill, usage: SkillUsage) -> bool:
        reason = runtime_omission_reason(used, usage)
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
        if skill.built_in_skill_id is None:
            charge = charges.get(skill.id) if charges is not None else None
            usage = charge.usage if charge is not None else None
            if charges is not None and usage is not None:
                if left_out(runtime_skill, usage):
                    continue
            bundle_bytes = _load_custom_bundle(
                runtime_skill, file_store, validity_updates
            )
            if bundle_bytes is None:
                continue
            if charges is not None and usage is None:
                usage = _bundle_runtime_usage(bundle_bytes) or SkillUsage()
                if left_out(runtime_skill, usage):
                    continue
            version = runtime_skill.version
            added = _add_bundle_bytes(
                files,
                runtime_skill.name,
                version.bundle_file_id if version is not None else None,
                bundle_bytes,
            )
            if added is _BundleAdd.ADDED and usage is not None:
                used += usage
            elif added is _BundleAdd.TOO_LARGE and usage is not None:
                # The files do not fit the transport cap although the charge
                # fits, for example after ${CLAUDE_SKILL_DIR} resolution.
                omissions.append(
                    SkillOmission(
                        plugin_id=skill.id,
                        name=runtime_skill.name,
                        bytes=usage.bytes,
                        files=usage.files,
                        reason="bytes",
                    )
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
        used += BUILT_IN_SKILL_RUNTIME_USAGE.get(
            definition.built_in_skill_id, SkillUsage()
        )

    _resolve_skill_dirs(files, sorted(seen_names))

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
    """``_assemble_skills`` without the run-time limit."""
    return _assemble_skills(skills, user, db_session, None).files


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
    charges = {
        charge.plugin_id: charge
        for charge in runtime_plugin_charges([user.id], db_session).get(user.id, [])
    }
    assembled = _assemble_skills(skills, user, db_session, charges)
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
