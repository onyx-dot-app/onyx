import csv
import tempfile
import uuid
import zipfile
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import get_all_empty_chat_message_entries
from ee.onyx.db.usage_export import write_usage_report
from ee.onyx.server.reporting.usage_export_models import UsageReportMetadata
from ee.onyx.server.reporting.usage_export_models import UserSkeleton
from onyx.configs.constants import FileOrigin
from onyx.db.users import get_all_users
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store


"""
Формирование CSV-отчёта о сообщениях
"""


def _prepare_report_period(
    period: tuple[datetime, datetime] | None
) -> tuple[datetime, datetime]:
    """Подготавливает временной период для отчета о сообщениях"""

    if period is None:
        # Если период не указан, берем всю историю
        start_time = datetime.fromtimestamp(0, tz=timezone.utc)
        end_time = datetime.now(tz=timezone.utc)
    else:
        # Корректируем конечное время для включения всего дня
        start_time = period[0]
        end_time = period[1] + timedelta(days=1)

    return start_time, end_time


def _write_chat_messages_to_csv(
    temp_file: tempfile.SpooledTemporaryFile,
    db_session: Session,
    report_period: tuple[datetime, datetime]
) -> None:
    """Записывает данные о сообщениях в CSV файл"""

    csv_writer = csv.writer(temp_file, delimiter=",")

    # Колонки CSV
    column_headers = ["session_id", "user_id", "flow_type", "time_sent"]
    csv_writer.writerow(column_headers)

    # Построчная запись данных
    message_batches = get_all_empty_chat_message_entries(
        db_session=db_session,
        period=report_period,
    )
    for message_batch in message_batches:
        for message_entry in message_batch:
            csv_writer.writerow([
                message_entry.chat_session_id,
                message_entry.user_id,
                message_entry.flow_type,
                message_entry.time_sent.isoformat(),
            ])


def generate_chat_messages_report(
    db_session: Session,
    file_store: FileStore,
    report_id: str,
    period: tuple[datetime, datetime] | None,
) -> str:
    """Генерирует CSV отчет по сообщениям чата за указанный период.

    Создает файл с информацией о сессиях, пользователях, типах потоков
    и времени отправки сообщений.

    Args:
        db_session: Сессия базы данных
        file_store: Хранилище файлов
        report_id: Идентификатор отчета
        period: Временной период (начало, конец)

    Returns:
        Название сохраненного файла
    """
    message_report_file_name = f"{report_id}_chat_sessions"

    # Подготовка временного диапазона
    report_period = _prepare_report_period(period)

    with tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE,
        mode="w+",
    ) as temp_csv:

        # Запись данных в CSV
        _write_chat_messages_to_csv(
            temp_file=temp_csv,
            db_session=db_session,
            report_period=report_period,
        )

        # Сброс позиции для чтения
        temp_csv.seek(0)

        # Сохранение в хранилище
        file_store.save_file(
            file_name=message_report_file_name,
            content=temp_csv,
            display_name=message_report_file_name,
            file_origin=FileOrigin.OTHER,
            file_type="text/csv",
        )

    return message_report_file_name


"""
Формирование CSV-отчёта о пользователях
"""


def _write_users_to_csv(
    temp_file: tempfile.SpooledTemporaryFile,
    users_data,
) -> None:
    """Записывает данные о пользователях в CSV файл"""

    csv_writer = csv.writer(temp_file, delimiter=",")

    # Колонки CSV
    column_headers = ["user_id", "is_active"]
    csv_writer.writerow(column_headers)

    # Запись данных пользователей
    for user_record in users_data:
        user_info = UserSkeleton(
            user_id=str(user_record.id),
            is_active=user_record.is_active,
        )
        csv_writer.writerow([user_info.user_id, user_info.is_active])


def generate_user_report(
    db_session: Session,
    file_store: FileStore,
    report_id: str,
) -> str:
    """Генерирует CSV отчет по пользователям системы.

    Создает файл с базовой информацией о пользователях:
    идентификаторы и статус активности.

    Args:
        db_session: Сессия базы данных
        file_store: Хранилище файлов
        report_id: Идентификатор отчета

    Returns:
        Название сохраненного файла
    """
    user_report_file_name = f"{report_id}_users"

    # Получение данных пользователей
    users_collection = get_all_users(db_session)

    with tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE,
        mode="w+",
    ) as temp_csv:

        # Запись данных в CSV
        _write_users_to_csv(
            temp_file=temp_csv,
            users_data=users_collection,
        )

        # Сброс позиции для чтения
        temp_csv.seek(0)

        # Сохранение в хранилище
        file_store.save_file(
            file_name=user_report_file_name,
            content=temp_csv,
            display_name=user_report_file_name,
            file_origin=FileOrigin.OTHER,
            file_type="text/csv",
        )

    return user_report_file_name


"""
Создание отчёта о пользователях и сообщениях системы
"""


def _save_zip_to_storage(
    storage: FileStore,
    filename: str,
    zip_data: tempfile.SpooledTemporaryFile
) -> None:
    """Сохраняет ZIP архив в файловое хранилище"""

    storage.save_file(
        file_name=filename,
        content=zip_data,
        display_name=filename,
        file_origin=FileOrigin.GENERATED_REPORT,
        file_type="application/zip",
    )


def _generate_report_filename(report_idx: str) -> str:
    """Генерирует имя файла для отчета"""

    current_date = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')
    report_filename = f"{current_date}_{report_idx}_usage_report.zip"

    return report_filename


def _build_report_metadata(report) -> UsageReportMetadata:
    """Создает объект метаданных отчета"""

    requestor_id = None
    if report.requestor_user_id:
        requestor_id = str(report.requestor_user_id)

    return UsageReportMetadata(
        report_name=report.report_name,
        requestor=requestor_id,
        time_created=report.time_created,
        period_from=report.period_from,
        period_to=report.period_to,
    )


def create_new_usage_report(
    db_session: Session,
    user_id: UUID_ID | None,
    period: tuple[datetime, datetime] | None,
) -> UsageReportMetadata:
    """Создает новый отчет об использовании системы
    и сохраняет его в хранилище.

    Генерирует два CSV файла (сообщения и пользователи), упаковывает в ZIP архив
    и сохраняет в файловом хранилище. Возвращает метаданные созданного отчета.

    Args:
        db_session: Сессия базы данных
        user_id: Идентификатор пользователя, запросившего отчет
        period: Временной период отчета (начало, конец)

    Returns:
        Метаданные созданного отчета
    """
    # Генерация уникального идентификатора отчета
    report_idx = str(uuid.uuid4())
    file_storage = get_default_file_store(db_session=db_session)

    # Формирование CSV файла с данными о сообщениях
    messages_filename = generate_chat_messages_report(
        db_session=db_session,
        file_store=file_storage,
        report_id=report_idx,
        period=period,
    )
    # Формирование CSV файла с данными о пользователях
    users_filename = generate_user_report(
        db_session=db_session,
        file_store=file_storage,
        report_id=report_idx,
    )

    # Создание ZIP архива с отчетами
    with tempfile.SpooledTemporaryFile(max_size=MAX_IN_MEMORY_SIZE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zip_file:
            # Добавление файла с сообщениями
            chat_messages_tmpfile = file_storage.read_file(
                messages_filename,
                mode="b",
                use_tempfile=True,
            )
            zip_file.writestr("chat_messages.csv", chat_messages_tmpfile.read())

            # Добавление файла с пользователями
            users_tmpfile = file_storage.read_file(
                users_filename,
                mode="b",
                use_tempfile=True,
            )
            zip_file.writestr("users.csv", users_tmpfile.read())

        zip_buffer.seek(0)

        # Создание названия файла и сохранение
        report_archive_filename = _generate_report_filename(report_idx=report_idx)
        _save_zip_to_storage(
            storage=file_storage,
            filename=report_archive_filename,
            zip_data=zip_buffer
        )

    # Запись метаданных отчета в базу
    report_record_db = write_usage_report(
        db_session=db_session,
        report_name=report_archive_filename,
        user_id=user_id,
        period=period,
    )

    return _build_report_metadata(report_record_db)
