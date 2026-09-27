"""Recording policy for incognito chat turns.

An incognito chat is an ordinary chat carrying a mode. ``IncognitoRecordMode``
is the only policy object: behavior is exposed as derived properties on it, so
the legal states are the only representable ones and no caller can assemble an
illegal combination out of loose booleans.

The contract that enforcement points must honor: an incognito session must pin
its mode on a metadata-only ``chat_session`` row at creation, and downstream
code must read the pinned value, never the live admin setting, so a setting
change cannot alter a session under way. Only FULL_HISTORY may write
conversation content into ``chat_message`` rows. USAGE_ONLY writes
content-free rows and must carry the live conversation outside Postgres
for the length of the session.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import is_chat_session_processing
from onyx.chat.incognito_context import (
    incognito_context_available,
    incognito_sessions_ended,
)
from onyx.configs.constants import INCOGNITO_FILE_CLEANUP_BATCH
from onyx.db.enums import IncognitoRecordMode, record_mode_persists_content
from onyx.db.file_record import (
    get_incognito_file_ids,
    get_session_ids_with_incognito_files,
)
from onyx.db.incognito import (
    mark_user_files_deleting,
    stale_incognito_session_ids,
    stale_unadopted_upload_ids,
    stale_upload_ids_for_sessions,
    touch_incognito_uploads_for_sessions,
    user_in_incognito_enabled_group,
)
from onyx.db.models import User
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LlmRequestPolicy
from onyx.llm.well_known_providers.constants import BIFROST_PROVIDER_NAME
from onyx.server.security.models import IncognitoAvailability
from onyx.server.security.store import get_security_settings, load_effective_uncached
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


def current_turn_persists_content() -> bool:
    mode = IncognitoRecordMode.from_context_value(get_current_incognito_record_mode())
    return record_mode_persists_content(mode)


def incognito_allowed_for_user(
    user: User, db_session: Session, *, cached: bool = True
) -> bool:
    """Whether this user may start an incognito chat.

    Availability composes the deployment capability (the ephemeral store must
    exist) with the admin's security setting, which defaults to off. Anonymous
    users never qualify: they share an identity, have no memberships, and
    cannot authenticate against the teardown endpoint.

    ``cached`` must be False wherever this decides an action rather than an
    affordance. Cache invalidation is process-local, so a second api_server can
    authorize against a revoked setting for the cache TTL.
    """
    if user.is_anonymous:
        return False
    if not incognito_context_available():
        return False
    settings = get_security_settings() if cached else load_effective_uncached()
    availability = settings.incognito_availability
    if availability is IncognitoAvailability.EVERYONE:
        return True
    if availability is IncognitoAvailability.GROUPS:
        return user_in_incognito_enabled_group(db_session, user.id)
    return False


# Bifrost's per-request switch for keeping content out of its gateway log.
# Honored only when the gateway enables allow_per_request_content_storage_override.
# Ignored otherwise, so this stays best effort from Onyx's side.
BIFROST_DISABLE_CONTENT_LOGGING_HEADER = "x-bf-disable-content-logging"
# Portkey "DO NOT TRACK": request/response content stays out of its logs,
# token/cost stats still record.
PORTKEY_DEBUG_HEADER = "x-portkey-debug"
# LiteLLM proxy per-request redaction: content stripped from its logs while
# spend rows still write, which incognito usage metering requires.
LITELLM_PROXY_REDACTION_HEADER = "x-litellm-enable-message-redaction"


def resolve_incognito_record_mode() -> IncognitoRecordMode:
    """The mode a new incognito session must pin: the workspace's admin
    record-mode setting, usage_only by default.

    Reads past the settings cache. Cache invalidation is process-local, so a
    second api_server can hold the pre-save mode for the cache TTL, and this
    read decides for the whole life of the session: pinning a stale
    full_history would persist content the admin has already disallowed.
    """
    return load_effective_uncached().incognito_record_mode


def sweep_stale_incognito_user_files(db_session: Session) -> list[UUID]:
    """Queue uploads of dead incognito sessions for deletion. Caller commits.

    Two passes, because the two shapes starve differently. Uploads no session
    ever claimed are deletable on sight. Uploads a session holds depend on that
    session's liveness, and are bounded by distinct sessions so one busy session
    cannot fill a pass. A live session keeps its attachments and its orphan
    clock restarts, so it does not occupy the next pass as well.
    """
    deletable = stale_unadopted_upload_ids(db_session)

    session_ids = stale_incognito_session_ids(db_session)
    ended = incognito_sessions_ended(session_ids)
    deletable += stale_upload_ids_for_sessions(db_session, sorted(ended))
    touch_incognito_uploads_for_sessions(
        db_session,
        [session_id for session_id in session_ids if session_id not in ended],
    )

    mark_user_files_deleting(db_session, deletable)
    return deletable


def sweep_incognito_generated_files(db_session: Session) -> None:
    """Retry deletion of tool-generated blobs a teardown pass failed to remove.

    A blob's record carries the session that produced it and deleting the blob
    deletes the record, so anything still stamped is what a store failure left
    behind. Shared by the Celery beat task and the lite drain, which is that
    deployment's only background pass.
    """
    cache = get_cache_backend()
    ended = incognito_sessions_ended(
        [
            UUID(raw_id)
            for raw_id in get_session_ids_with_incognito_files(
                db_session, limit=INCOGNITO_FILE_CLEANUP_BATCH
            )
        ]
    )
    for session_id in ended:
        # A turn in flight owns its files, and an evicted context reads as
        # ended, so the processing fence decides, not the context.
        if is_chat_session_processing(session_id, cache):
            continue
        try:
            delete_incognito_generated_files(session_id, db_session)
        except Exception:
            # One unreachable blob must not strand every session behind it.
            logger.exception("Incognito file cleanup failed for session %s", session_id)


def incognito_llm_extra_headers(
    mode: IncognitoRecordMode | None,
    provider: str | None,
) -> dict[str, str]:
    """Headers an LLM request must carry under this recording mode.

    Only Bifrost honors a per-request retention switch. FULL_HISTORY sends
    nothing: the workspace chose to record content, and the gateway log is the
    workspace's own infrastructure.

    Pass the result as ``get_llm``'s ``policy_headers`` so it outranks request,
    deployment-env, and provider header sources. Merged anywhere earlier, a
    deployment-wide header could silently re-enable gateway content logging.
    """
    if record_mode_persists_content(mode):
        return {}
    if provider == BIFROST_PROVIDER_NAME:
        return {BIFROST_DISABLE_CONTENT_LOGGING_HEADER: "true"}
    if provider == LlmProviderNames.PORTKEY.value:
        return {PORTKEY_DEBUG_HEADER: "false"}
    if provider == LlmProviderNames.LITELLM_PROXY.value:
        return {LITELLM_PROXY_REDACTION_HEADER: "true"}
    return {}


def incognito_llm_extra_body(
    mode: IncognitoRecordMode | None,
    provider: str | None,
) -> dict[str, Any]:
    """Request-body params a content-free turn must carry, by provider.

    Merged last into model kwargs for the same reason the headers are: a
    deployment-wide param must not re-enable provider-side retention.
    """
    if record_mode_persists_content(mode):
        return {}
    # OpenAI Responses API stores by default for 30 days, and Chat Completions
    # accepts the same param. Azure's stored-completions opt-in stays off.
    if provider in (
        LlmProviderNames.OPENAI.value,
        LlmProviderNames.AZURE.value,
    ):
        return {"store": False}
    # Routes only to OpenRouter endpoints that do not retain user data.
    if provider == LlmProviderNames.OPENROUTER.value:
        return {"extra_body": {"provider": {"data_collection": "deny"}}}
    return {}


def incognito_llm_request_policy(
    mode: IncognitoRecordMode | None,
    provider: str | None,
) -> LlmRequestPolicy:
    """The per-provider retention suppression a turn under this mode carries.

    Providers with no per-request option (Anthropic, Google, Vertex, Mistral,
    Bedrock, Nebius, local servers) get an empty policy: their retention is an
    account or deployment concern, which the incognito disclaimer covers.
    """
    return LlmRequestPolicy(
        headers=incognito_llm_extra_headers(mode, provider),
        model_kwargs=incognito_llm_extra_body(mode, provider),
    )


def content_free_file_descriptors(
    file_descriptors: list[FileDescriptor],
) -> list[FileDescriptor]:
    """Descriptors safe to persist for a content-free turn. Linkage ids and
    type survive for the file-reader tool and teardown. The content-derived
    filename does not."""
    return [
        FileDescriptor(
            id=fd["id"], type=fd["type"], user_file_id=fd.get("user_file_id")
        )
        for fd in file_descriptors
    ]


def delete_incognito_generated_files(
    chat_session_id: UUID, db_session: Session
) -> bool:
    """Delete the blobs the session's tools saved. True when none remain.

    The file record carries the session stamp, so deleting the blob deletes the
    handle with it. A blob the store refuses keeps both, which is what the
    cleanup sweep retries from."""
    file_store = get_default_file_store()
    outstanding = False
    for file_id in get_incognito_file_ids(str(chat_session_id), db_session):
        try:
            file_store.delete_file(file_id, error_on_missing=False)
        except Exception:
            logger.warning("Failed to delete incognito generated file %s", file_id)
            outstanding = True
    return not outstanding
