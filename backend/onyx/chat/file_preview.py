"""The PDF preview of a PowerPoint or Word chat file: the stored PDF that
`GET /chat/file/{file_id}?preview=pdf` serves, and the conversion that
`POST /chat/file/{file_id}/preview` runs."""

from io import BytesIO
from typing import IO
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.chat import (
    get_chat_file_preview_row,
    link_chat_file_preview,
    save_chat_file_preview,
)
from onyx.db.models import ChatArtifactVersion, FileRecord, UserFile
from onyx.db.sandbox import get_or_create_sandbox
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.file_types import (
    OFFICE_MIME_TYPES_BY_EXTENSION,
    guess_mime_type,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.microvm.agent_client import HostAgentError
from onyx.microvm.daemon_client import SandboxDaemonError
from onyx.microvm.lifecycle import SandboxVmUnusableError
from onyx.server.features.build.sandbox.harness_base import (
    RENDER_PREVIEW_BUDGET_SECONDS,
    RENDER_PREVIEW_MAX_INPUT_BYTES,
    RENDER_PREVIEW_PDF_MIME_TYPES,
    RenderBudgetSpentError,
)
from onyx.server.features.build.sandbox.harness_factory import (
    HarnessSandboxUnavailableError,
    get_harness_sandbox,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxKey,
    RenderFileBytes,
    SandboxProvisionContentionError,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def resolve_chat_file_preview(
    db_session: Session, file_record: FileRecord
) -> tuple[ChatArtifactVersion | UserFile, UUID, str]:
    """The row whose preview PDF link serves the chat file `file_record`
    (get_chat_file_preview_row), the ID of the user who owns the file, and
    the file's MIME type. Raises OnyxError PREVIEW_UNAVAILABLE when the file
    is not a PowerPoint or Word file, or it has no preview row (no artifact
    version or user file owns it, or its user file is being deleted)."""
    mime_type = (
        file_record.file_type
        if file_record.file_type in RENDER_PREVIEW_PDF_MIME_TYPES
        else guess_mime_type(file_record.display_name or file_record.file_id)
    )
    preview_row = (
        get_chat_file_preview_row(db_session, file_record.file_id)
        if mime_type in RENDER_PREVIEW_PDF_MIME_TYPES
        else None
    )
    if preview_row is None or mime_type is None:
        raise OnyxError(
            OnyxErrorCode.PREVIEW_UNAVAILABLE, "This file has no PDF preview"
        )
    return preview_row[0], preview_row[1], mime_type


def read_stored_chat_file_preview(
    db_session: Session, file_record: FileRecord
) -> IO[bytes] | None:
    """The stored PDF preview of the chat file `file_record`, or None when
    none is made yet. Raises OnyxError PREVIEW_UNAVAILABLE when the file has
    no PDF preview (resolve_chat_file_preview)."""
    preview_row, _, _ = resolve_chat_file_preview(db_session, file_record)
    if preview_row.preview_file_id is None:
        return None
    return get_default_file_store().read_file(
        preview_row.preview_file_id, mode="b", use_tempfile=True
    )


def convert_chat_file_preview_pdf(
    db_session: Session, file_record: FileRecord
) -> IO[bytes]:
    """The PDF preview of the chat file `file_record`, which the caller
    checked that the requesting user can read: the stored PDF, else the PDF
    that the sandbox of the file's owner converts, whoever asks, which this
    saves and links. A publish converts in the publisher's sandbox, and the
    publisher is the owner, so a stored PDF has the same trust as its file.
    Two first conversions at once both convert; the first link wins, and
    the other deletes its own copy.

    Raises OnyxError PREVIEW_UNAVAILABLE when the file has no PDF preview
    now: not a PowerPoint or Word file, no preview row (no artifact version
    or user file owns it, or its user file is being deleted), it is too
    large, the converter rejects it or does not finish within the
    render budget, or the deployment has no sandbox. Nothing is saved then,
    so a later request tries again. Raises OnyxError SERVICE_UNAVAILABLE or
    SANDBOX_CAPACITY_UNAVAILABLE when the sandbox cannot start or be reached
    now."""
    stored = read_stored_chat_file_preview(db_session, file_record)
    if stored is not None:
        return stored
    preview_row, owner_id, mime_type = resolve_chat_file_preview(
        db_session, file_record
    )
    file_id = file_record.file_id
    file_name = file_record.display_name or file_id
    file_store = get_default_file_store()
    try:
        sandbox = get_harness_sandbox()
    except HarnessSandboxUnavailableError as e:
        raise OnyxError(
            OnyxErrorCode.PREVIEW_UNAVAILABLE,
            "This deployment has no sandbox to convert the file",
        ) from e
    data = b""
    if (file_record.file_size or 0) <= RENDER_PREVIEW_MAX_INPUT_BYTES:
        # A temporary file holds the source, whose recorded size can be
        # missing.
        with file_store.read_file(file_id, mode="b", use_tempfile=True) as source:
            data = source.read(RENDER_PREVIEW_MAX_INPUT_BYTES + 1)
    if not data or len(data) > RENDER_PREVIEW_MAX_INPUT_BYTES:
        raise OnyxError(
            OnyxErrorCode.PREVIEW_UNAVAILABLE,
            "The file is empty or too large to convert",
        )
    render_source = RenderFileBytes(
        sandbox=HarnessSandboxKey(
            tenant_id=get_current_tenant_id(),
            sandbox_id=get_or_create_sandbox(db_session, owner_id).id,
        ),
        suffix=next(
            suffix
            for suffix, office_type in OFFICE_MIME_TYPES_BY_EXTENSION.items()
            if office_type == mime_type
        ),
        data=data,
    )
    # The render holds no database transaction.
    db_session.commit()
    try:
        rendered = sandbox.render_preview(
            render_source,
            first_page=False,
            budget_seconds=RENDER_PREVIEW_BUDGET_SECONDS,
        )
    except RenderBudgetSpentError as e:
        # The budget starts once the VM runs, so a retry of the file most
        # likely runs out of it too.
        logger.warning("chat_file_preview_budget_spent file=%s", file_id)
        raise OnyxError(
            OnyxErrorCode.PREVIEW_UNAVAILABLE,
            "The file takes too long to convert to a PDF",
        ) from e
    except (
        HostAgentError,
        SandboxDaemonError,
        SandboxProvisionContentionError,
        SandboxVmUnusableError,
    ) as e:
        logger.warning(
            "chat_file_preview_sandbox_failed file=%s", file_id, exc_info=True
        )
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "The sandbox cannot convert the file now. Try again.",
        ) from e
    if rendered is None or rendered.pdf is None:
        raise OnyxError(
            OnyxErrorCode.PREVIEW_UNAVAILABLE,
            "The file could not be converted to a PDF that can be previewed",
        )
    saved_file_id = save_chat_file_preview(BytesIO(rendered.pdf), file_name)
    try:
        linked = link_chat_file_preview(db_session, preview_row, saved_file_id)
    except BaseException:
        delete_files_best_effort([saved_file_id], "unlinked chat file preview")
        raise
    if not linked:
        # Another conversion linked its PDF first, or the file is gone or
        # being deleted.
        delete_files_best_effort([saved_file_id], "unlinked chat file preview")
    return BytesIO(rendered.pdf)
