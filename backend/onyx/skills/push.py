"""Push skill bundles to running sandboxes."""

import hashlib
import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.models import Skill, User
from onyx.db.skill import (
    RuntimeSkillCandidate,
    SkillValidityUpdate,
    affected_user_ids_for_skill,
    list_runtime_skill_candidates_for_user,
    persist_skill_validity,
)
from onyx.db.skill_runtime_models import SkillRuntimeLimit, SkillRuntimeOmission
from onyx.file_processing.zip_index import ZipIndex
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.build.db.sandbox import (
    get_sandbox_user_map,
    lock_sandbox_skills_hashes,
    set_sandbox_skills_hashes__no_commit,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    PUSH_MAX_DIRECTORIES,
    PUSH_MAX_FILE_BYTES,
    PUSH_VERSION_NAME_BYTES,
    push_parent_directories,
    push_path_byte_limit,
    push_version_directory,
    validate_push_path,
)
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.session_workspace import SESSIONS_ROOT
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
)
from onyx.skills.rendering import (
    CLAUDE_SKILL_DIR_PLACEHOLDER,
    render_company_search_skill,
    render_external_app_files,
)
from onyx.skills.validation import (
    load_stored_custom_skill_bundle,
    validate_stored_custom_skill,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

SKILLS_MOUNT_PATH = "/workspace/managed/skills"
SKILL_RUNTIME_MAX_PATH_BYTES = min(
    push_path_byte_limit(
        str(push_version_directory(SKILLS_MOUNT_PATH, "0" * PUSH_VERSION_NAME_BYTES))
    ),
    # Files must also open through the session's longer symlink path.
    push_path_byte_limit(f"{SESSIONS_ROOT}/{UUID(int=0)}/.opencode/skills"),
)

# Runtime skill disk budget, in binary units as the bundle limits use.
SKILL_RUNTIME_MAX_BYTES = 900 * 1024 * 1024
SKILL_RUNTIME_MAX_FILES = 10_000
# Each rendered file uses at least one 4 KiB filesystem block.
SKILL_RUNTIME_MIN_FILE_CHARGE_BYTES = 4 * 1024


class _OverLimitFileSet(dict[str, bytes]):
    """A candidate with more files than any runtime payload accepts.

    It keeps SKILL.md and SKILL_RUNTIME_MAX_FILES files, and only counts the
    rest, so the omission reports the same totals without their contents.
    """

    counted_files = 0
    counted_bytes = 0


def _charged_bytes(candidate_files: FileSet) -> int:
    charged = sum(
        max(_resolved_file_size(path, content), SKILL_RUNTIME_MIN_FILE_CHARGE_BYTES)
        for path, content in candidate_files.items()
    )
    if isinstance(candidate_files, _OverLimitFileSet):
        charged += candidate_files.counted_bytes
    return charged


def _file_count(candidate_files: FileSet) -> int:
    if isinstance(candidate_files, _OverLimitFileSet):
        return len(candidate_files) + candidate_files.counted_files
    return len(candidate_files)


@dataclass(frozen=True)
class RuntimeSkillSelection:
    files: FileSet
    omissions: tuple[SkillRuntimeOmission, ...]


@dataclass(frozen=True)
class UserSkillsPayload:
    files: FileSet
    omissions: tuple[SkillRuntimeOmission, ...]
    connectable_apps_section: str


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


def _add_bundle_bytes(files: FileSet, skill: Skill, bundle_bytes: bytes) -> FileSet:
    """Add a normalized bundle, whose paths are unique, to ``files``."""
    skill_md_path = f"{skill.name}/{SKILL_MD_NAME}"
    with ZipIndex(bundle_bytes) as zf:
        for info in zf.infos():
            if info.is_dir():
                continue
            path = f"{skill.name}/{info.filename}"
            with zf.open(info) as source:
                content = source.read()
            if len(files) < SKILL_RUNTIME_MAX_FILES or path == skill_md_path:
                files[path] = content
                continue
            if not isinstance(files, _OverLimitFileSet):
                files = _OverLimitFileSet(files)
            files.counted_files += 1
            files.counted_bytes += max(
                len(content), SKILL_RUNTIME_MIN_FILE_CHARGE_BYTES
            )
    return files


def _resolved_file_size(path: str, content: bytes) -> int:
    name, _, relative = path.partition("/")
    if relative != SKILL_MD_NAME:
        return len(content)
    placeholder = CLAUDE_SKILL_DIR_PLACEHOLDER.encode()
    return len(content) + content.count(placeholder) * (
        len(f"{SKILLS_MOUNT_PATH}/{name}".encode()) - len(placeholder)
    )


def _resolve_skill_dirs(files: FileSet, skill_names: Iterable[str]) -> None:
    """Point ``${CLAUDE_SKILL_DIR}`` in each root ``SKILL.md`` at the skill's
    sandbox folder. Only the sent copy changes, not the stored bundle."""
    placeholder = CLAUDE_SKILL_DIR_PLACEHOLDER.encode()
    for name in skill_names:
        path = f"{name}/{SKILL_MD_NAME}"
        content = files.get(path)
        if content is None or placeholder not in content:
            continue
        files[path] = content.replace(
            placeholder, f"{SKILLS_MOUNT_PATH}/{name}".encode()
        )


def _render_candidate(
    skill: Skill,
    user: User,
    db_session: Session,
    file_store: FileStore,
    validity_updates: dict[UUID, SkillValidityUpdate],
) -> FileSet | None:
    """Render one complete candidate, or return None so delivery tries the next.

    Stage each candidate separately so read, unpack, or render failures cannot
    reserve a name or leak partial files into the next candidate's bundle.
    """
    candidate_files: FileSet = {}
    try:
        if skill.built_in_skill_id is None:
            version = skill.current_version
            if version is None or version.is_valid is False:
                return None

            if version.is_valid is None:
                validation = validate_stored_custom_skill(skill, file_store)
                if validation.is_valid is not None:
                    validity_updates[version.id] = SkillValidityUpdate(
                        skill_id=skill.id,
                        version_id=version.id,
                        bundle_file_id=version.bundle_file_id,
                        is_valid=validation.is_valid,
                    )
                if validation.normalized_bundle is None:
                    logger.warning(
                        "Skipping unvalidated skill %s: %s",
                        skill.id,
                        validation.detail,
                    )
                    return None
                bundle_bytes = validation.normalized_bundle
            else:
                if version.bundle_file_id is None:
                    return None
                bundle_bytes = load_stored_custom_skill_bundle(
                    version.bundle_file_id,
                    file_store,
                ).content
            candidate_files = _add_bundle_bytes(candidate_files, skill, bundle_bytes)
        else:
            definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
            if definition is None:
                logger.warning(
                    "Skill row %s references unknown built-in %s; skipping",
                    skill.name,
                    skill.built_in_skill_id,
                )
                return None
            _add_static_builtin(candidate_files, skill, definition)
            if definition.has_template:
                _render_template(candidate_files, skill, definition, db_session, user)

        if f"{skill.name}/{SKILL_MD_NAME}" not in candidate_files:
            logger.warning("Skipping skill %s without instructions", skill.id)
            return None
        instructions = candidate_files[f"{skill.name}/{SKILL_MD_NAME}"]
        if CLAUDE_SKILL_DIR_PLACEHOLDER.encode() in instructions:
            instructions.decode("utf-8")
    except Exception:
        logger.warning("Failed to assemble skill %s; skipping", skill.id, exc_info=True)
        return None
    return candidate_files


def _assemble_fileset(
    candidates: Iterable[RuntimeSkillCandidate],
    user: User,
    db_session: Session,
) -> RuntimeSkillSelection:
    """Deliver the first complete candidate for each name within the runtime limit.

    Names are processed by the best keep rank any remaining candidate could
    deliver. If the delivered candidate ranks after another pending name, its
    files are dropped and the name is rendered again at its real rank. Only
    the selected files and one candidate are in memory at a time. A delivered
    candidate that does not fit is omitted whole; no duplicate replaces it.
    """
    pending: dict[str, list[RuntimeSkillCandidate]] = {}
    for candidate in candidates:
        pending.setdefault(candidate.skill.name, []).append(candidate)
    queue = [
        (min(c.keep_rank for c in name_candidates), name)
        for name, name_candidates in pending.items()
    ]
    heapq.heapify(queue)

    files: FileSet = {}
    omissions: list[SkillRuntimeOmission] = []
    charged_bytes = 0
    file_count = 0
    directories: set[str] = set()
    validity_updates: dict[UUID, SkillValidityUpdate] = {}
    file_store = get_default_file_store()

    while queue:
        _, name = heapq.heappop(queue)
        remaining = pending[name]
        while remaining:
            candidate = remaining[0]
            candidate_files = _render_candidate(
                candidate.skill, user, db_session, file_store, validity_updates
            )
            if candidate_files is not None:
                break
            remaining.pop(0)
        else:
            continue
        if queue and queue[0][0] < candidate.keep_rank:
            del candidate_files
            heapq.heappush(queue, (candidate.keep_rank, name))
            continue

        skill_bytes = _charged_bytes(candidate_files)
        skill_files = _file_count(candidate_files)
        failed_limit: SkillRuntimeLimit | None = None
        if charged_bytes + skill_bytes > SKILL_RUNTIME_MAX_BYTES or any(
            _resolved_file_size(path, content)
            > min(DEFAULT_PER_FILE_MAX_BYTES, PUSH_MAX_FILE_BYTES)
            for path, content in candidate_files.items()
        ):
            failed_limit = SkillRuntimeLimit.BYTES
        elif file_count + skill_files > SKILL_RUNTIME_MAX_FILES:
            failed_limit = SkillRuntimeLimit.FILES
        skill_directories: set[str] = set()
        if failed_limit is None:
            for path in candidate_files:
                try:
                    validate_push_path(path, SKILL_RUNTIME_MAX_PATH_BYTES)
                except ValueError:
                    failed_limit = SkillRuntimeLimit.PATHS
                    break
                for directory in push_parent_directories(path):
                    if directory in directories or directory in skill_directories:
                        break
                    skill_directories.add(directory)
                    if len(directories) + len(skill_directories) > PUSH_MAX_DIRECTORIES:
                        failed_limit = SkillRuntimeLimit.DIRECTORIES
                        break
                if failed_limit is not None:
                    break
        if failed_limit is None:
            _resolve_skill_dirs(candidate_files, [name])
            files.update(candidate_files)
            charged_bytes += skill_bytes
            file_count += skill_files
            directories.update(skill_directories)
        else:
            omissions.append(
                SkillRuntimeOmission(
                    skill_id=candidate.skill.id,
                    name=name,
                    charged_bytes=skill_bytes,
                    file_count=skill_files,
                    failed_limit=failed_limit,
                )
            )
        del candidate_files

    try:
        persist_skill_validity(list(validity_updates.values()))
    except Exception:
        logger.exception("Failed to persist skill validity classifications")
    return RuntimeSkillSelection(files=files, omissions=tuple(omissions))


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return the ``{path: bytes}`` map that fits the user's runtime limit."""
    candidates = list_runtime_skill_candidates_for_user(
        user=user, db_session=db_session
    )
    return _assemble_fileset(candidates, user, db_session).files


def build_user_skills_payload(user: User, db_session: Session) -> UserSkillsPayload:
    """Return the skill files within the runtime limit, omissions and app guidance.

    The connectable-apps section lists org apps the user has not connected yet,
    so the agent can offer to set one up through the connect tool.
    """
    candidates = list_runtime_skill_candidates_for_user(
        user=user, db_session=db_session
    )
    selection = _assemble_fileset(candidates, user, db_session)
    connectable_apps_section = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    return UserSkillsPayload(
        files=selection.files,
        omissions=selection.omissions,
        connectable_apps_section=connectable_apps_section,
    )


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
        successful_hashes: dict[UUID, str] = {}
        targets = 0
        failures = 0
        for sandbox_id, user in sandbox_map.items():
            targets += 1
            payload: UserSkillsPayload | None = None
            try:
                payload = build_user_skills_payload(user, db_session)
                desired_hash = compute_skill_runtime_hash(
                    payload.files, payload.connectable_apps_section
                )
                if current_hashes.get(sandbox_id) == desired_hash:
                    targets -= 1
                    continue
                result = get_sandbox_manager().push_to_sandbox(
                    sandbox_id=sandbox_id,
                    mount_path=SKILLS_MOUNT_PATH,
                    files=payload.files,
                )
                for failure in result.failures:
                    logger.warning(
                        "Skill push failed for sandbox %s: %s: %s",
                        failure.sandbox_id,
                        failure.reason,
                        failure.detail,
                    )
                if result.succeeded == 1 and not result.failures:
                    successful_hashes[sandbox_id] = desired_hash
                else:
                    failures += 1
            except Exception:
                failures += 1
                logger.exception(
                    "Failed to build or push skills for sandbox %s", sandbox_id
                )
            finally:
                # Release the current payload before the next one is constructed.
                del payload
        if failures:
            logger.warning("Skill push: %d/%d targets failed", failures, targets)
        if not successful_hashes:
            return
        try:
            with db_session.begin_nested():
                set_sandbox_skills_hashes__no_commit(
                    db_session,
                    successful_hashes,
                )
        except Exception:
            logger.exception("Failed to persist successful skill push state")
    except Exception:
        logger.exception("Failed to push skills to sandboxes")
