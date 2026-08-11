import csv
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import (
    get_all_empty_chat_message_entries,
    usage_report_id_in_use,
    write_usage_report,
)
from ee.onyx.server.reporting.usage_export_models import (
    UsageReportMetadata,
    UserSkeleton,
)
from ee.onyx.server.reporting.usage_report_branding import load_report_branding
from ee.onyx.server.reporting.usage_report_data import build_usage_report_data
from ee.onyx.server.reporting.usage_report_pdf import render_usage_report_pdf
from onyx.configs.constants import FileOrigin
from onyx.db.models import User
from onyx.db.user_usage import UsageExportRow, iter_usage_export
from onyx.db.users import get_all_users
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.utils.csv_utils import sanitize_csv_cell_or_none
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _normalize_period(
    period: tuple[datetime, datetime] | None,
) -> tuple[datetime, datetime]:
    if period is None:
        return (
            datetime.fromtimestamp(0, tz=timezone.utc),
            datetime.now(tz=timezone.utc),
        )
    # time-picker sends a time which is at the beginning of the day
    # so we need to add one day to the end time to make it inclusive
    return (period[0], period[1] + timedelta(days=1))


def generate_chat_messages_report(
    db_session: Session,
    file_store: FileStore,
    report_id: str,
    period: tuple[datetime, datetime],
) -> str:
    file_name = f"{report_id}_chat_sessions"

    with tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE, mode="w+"
    ) as temp_file:
        csvwriter = csv.writer(temp_file, delimiter=",")
        csvwriter.writerow(
            [
                "session_id",
                "user_id",
                "flow_type",
                "time_sent",
                "assistant_name",
                "user_email",
                "number_of_tokens",
                "llm_model",
            ]
        )
        for chat_message_skeleton_batch in get_all_empty_chat_message_entries(
            db_session, period
        ):
            for chat_message_skeleton in chat_message_skeleton_batch:
                # assistant_name and user_email are user-supplied — sanitize
                # to prevent CSV/formula injection against whoever opens the
                # report in a spreadsheet. The remaining fields are
                # system-generated (UUIDs, enums, timestamps, ints).
                csvwriter.writerow(
                    [
                        chat_message_skeleton.chat_session_id,
                        chat_message_skeleton.user_id,
                        chat_message_skeleton.flow_type,
                        chat_message_skeleton.time_sent.isoformat(),
                        sanitize_csv_cell_or_none(chat_message_skeleton.assistant_name),
                        sanitize_csv_cell_or_none(chat_message_skeleton.user_email),
                        chat_message_skeleton.number_of_tokens,
                        chat_message_skeleton.llm_model,
                    ]
                )

        # after writing seek to beginning of buffer
        temp_file.seek(0)
        file_id = file_store.save_file(
            content=temp_file,
            display_name=file_name,
            file_origin=FileOrigin.GENERATED_REPORT,
            file_type="text/csv",
        )

    return file_id


def generate_user_report(
    db_session: Session,
    file_store: FileStore,
    report_id: str,
) -> str:
    file_name = f"{report_id}_users"

    with tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE, mode="w+"
    ) as temp_file:
        csvwriter = csv.writer(temp_file, delimiter=",")
        csvwriter.writerow(["user_id", "is_active"])

        users = get_all_users(db_session)
        for user in users:
            user_skeleton = UserSkeleton(
                user_id=str(user.id),
                is_active=user.is_active,
            )
            csvwriter.writerow([user_skeleton.user_id, user_skeleton.is_active])

        temp_file.seek(0)
        file_id = file_store.save_file(
            content=temp_file,
            display_name=file_name,
            file_origin=FileOrigin.GENERATED_REPORT,
            file_type="text/csv",
        )

    return file_id


def generate_usage_breakdown_report(
    file_store: FileStore,
    report_id: str,
    rows: Iterable[UsageExportRow],
) -> str:
    file_name = f"{report_id}_usage_by_user"

    with tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE, mode="w+"
    ) as temp_file:
        csvwriter = csv.writer(temp_file, delimiter=",")
        csvwriter.writerow(
            [
                "user_email",
                "day",
                "model",
                "flow",
                "provider",
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cost_cents",
            ]
        )
        for row in rows:
            # User-controlled strings: formula-injection guard.
            csvwriter.writerow(
                [
                    sanitize_csv_cell_or_none(row.email),
                    row.day,
                    sanitize_csv_cell_or_none(row.model),
                    sanitize_csv_cell_or_none(row.flow),
                    sanitize_csv_cell_or_none(row.provider),
                    row.input_tokens,
                    row.output_tokens,
                    row.cache_read_tokens,
                    row.cost_cents,
                ]
            )

        temp_file.seek(0)
        file_id = file_store.save_file(
            content=temp_file,
            display_name=file_name,
            file_origin=FileOrigin.GENERATED_REPORT,
            file_type="text/csv",
        )

    return file_id


def generate_usage_report_pdf(
    db_session: Session,
    file_store: FileStore,
    report_id: str,
    period: tuple[datetime, datetime] | None,
    rows: list[UsageExportRow],
) -> str:
    """Render the review pack PDF and store it. Returns the file id."""
    file_name = f"{report_id}_review_pack"

    # The queried bounds are half-open; only a given period gets the extra day.
    display_start, display_end = period if period else _normalize_period(None)

    data = build_usage_report_data(db_session, rows, display_start, display_end)
    branding = load_report_branding(file_store)
    pdf_bytes = render_usage_report_pdf(data, branding)

    return file_store.save_file(
        content=BytesIO(pdf_bytes),
        display_name=file_name,
        file_origin=FileOrigin.GENERATED_REPORT,
        file_type="application/pdf",
    )


def create_new_usage_report(
    db_session: Session,
    user_id: UUID_ID | None,  # None = auto-generated
    period: tuple[datetime, datetime] | None,
    report_id: str | None = None,
) -> UsageReportMetadata:
    report_id = report_id or str(uuid.uuid4())
    file_store = get_default_file_store()
    normalized_period = _normalize_period(period)

    intermediate_file_ids: list[str] = []
    try:
        messages_file_id = generate_chat_messages_report(
            db_session, file_store, report_id, normalized_period
        )
        intermediate_file_ids.append(messages_file_id)
        users_file_id = generate_user_report(db_session, file_store, report_id)
        intermediate_file_ids.append(users_file_id)

        query_start, query_end = normalized_period
        # The CSV and PDF must use the same rows so their totals reconcile.
        usage_rows = list(iter_usage_export(db_session, query_start, query_end))
        usage_breakdown_file_id = generate_usage_breakdown_report(
            file_store, report_id, usage_rows
        )
        intermediate_file_ids.append(usage_breakdown_file_id)

        # A render failure must not cost the admin their CSV export.
        pdf_file_id: str | None = None
        try:
            pdf_file_id = generate_usage_report_pdf(
                db_session, file_store, report_id, period, usage_rows
            )
        except Exception:
            logger.exception("Failed to render usage report PDF; continuing without it")
        else:
            intermediate_file_ids.append(pdf_file_id)

        # Re-check just before writing the final report: the API-level check
        # happens before this (async) task runs, so a second request with the
        # same client-supplied report_id can slip past it while this task is
        # still generating the first report.
        if usage_report_id_in_use(db_session, uuid.UUID(report_id)):
            raise ValueError(f"report_id {report_id} is already in use")

        with tempfile.SpooledTemporaryFile(max_size=MAX_IN_MEMORY_SIZE) as zip_buffer:
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
                # write messages
                chat_messages_tmpfile = file_store.read_file(
                    messages_file_id, mode="b", use_tempfile=True
                )
                zip_file.writestr(
                    "chat_messages.csv",
                    chat_messages_tmpfile.read(),
                )

                # write users
                users_tmpfile = file_store.read_file(
                    users_file_id, mode="b", use_tempfile=True
                )
                zip_file.writestr("users.csv", users_tmpfile.read())

                usage_breakdown_tmpfile = file_store.read_file(
                    usage_breakdown_file_id, mode="b", use_tempfile=True
                )
                zip_file.writestr("usage_by_user.csv", usage_breakdown_tmpfile.read())

                if pdf_file_id is not None:
                    pdf_tmpfile = file_store.read_file(
                        pdf_file_id, mode="b", use_tempfile=True
                    )
                    zip_file.writestr("usage_report.pdf", pdf_tmpfile.read())

            zip_buffer.seek(0)

            # store zip blob to file_store
            report_name = f"{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}_{report_id}_usage_report.zip"
            file_store.save_file(
                content=zip_buffer,
                display_name=report_name,
                file_origin=FileOrigin.GENERATED_REPORT,
                file_type="application/zip",
                file_id=report_name,
            )
    finally:
        for file_id in intermediate_file_ids:
            try:
                file_store.delete_file(file_id, error_on_missing=False)
            except Exception:
                logger.exception(
                    "Failed to delete temporary usage report file %s", file_id
                )

    # add report after zip file is written
    new_report = write_usage_report(db_session, report_name, user_id, period)

    # get user email
    requestor_user = (
        db_session.query(User)
        .filter(cast(User.id, UUID) == new_report.requestor_user_id)
        .one_or_none()
        if new_report.requestor_user_id
        else None
    )
    requestor_email = requestor_user.email if requestor_user else None

    return UsageReportMetadata(
        report_name=new_report.report_name,
        requestor=requestor_email,
        time_created=new_report.time_created,
        period_from=new_report.period_from,
        period_to=new_report.period_to,
    )
