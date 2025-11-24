from collections.abc import Generator
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from smartsearch.onyx.db.usage_export import (
    get_all_usage_reports,
    get_usage_report_data,
    UsageReportMetadata,
)
from smartsearch.onyx.server.reporting.usage_export_generation import create_new_usage_report
from smartsearch.onyx.server.reporting.usage_export_models import GenerateUsageReportParams
from onyx.auth.users import current_admin_user
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.file_store.constants import STANDARD_CHUNK_SIZE

router = APIRouter(tags=["Отчёты об использовании системы"])


@router.post(
    "/admin/generate-usage-report",
    summary="Генерация отчета об использовании системы",
    response_model=UsageReportMetadata,
)
def generate_report(
    params: GenerateUsageReportParams,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> UsageReportMetadata:
    """Генерация комплексного отчета об использовании системы.

    Создает ZIP-архив с двумя CSV файлами:
        - chat_messages.csv: статистика по сообщениям и сессиям
        - users.csv: информация о пользователях и их активности

    Отчет сохраняется в файловом хранилище и доступен для скачивания.

    Args:
        params: Параметры периода для отчета
        user: Текущий администратор

    Returns:
        Метаданные созданного отчета
    """
    selected_interval = None
    if params.period_from and params.period_to:
        try:
            start_point = datetime.fromisoformat(params.period_from)
            end_point = datetime.fromisoformat(params.period_to)
            selected_interval = (start_point, end_point)
        except ValueError as conversion_error:
            raise HTTPException(
                status_code=400,
                detail=f"Ошибка формата даты: {conversion_error}"
            )

    if user:
        user_id = user.id
    else:
        user_id = None

    report_data = create_new_usage_report(
        db_session=db_session,
        user_id=user_id,
        period=selected_interval,
    )

    return report_data


@router.get(
    "/admin/usage-report/{report_name}",
    summary="Скачивание сгенерированного отчета по использованию системы"
)
def read_usage_report(
    report_name: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Скачивание сгенерированного отчета по использованию системы.

    Потоковая передача ZIP-архива с данными отчета. Архив содержит
    CSV файлы с статистикой сообщений и информацией о пользователях.

    Args:
        report_name: Название файла отчета для скачивания

    Returns:
        Потоковый ответ с ZIP-архивом отчета
    """
    try:
        report_file = get_usage_report_data(
            db_session=db_session,
            report_name=report_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    def iterfile() -> Generator[bytes, None, None]:
        while True:
            chunk = report_file.read(STANDARD_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        content=iterfile(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={report_name}"},
    )


@router.get(
    "/admin/usage-report",
    summary="Получение списка всех сгенерированных отчетов по использованию системы",
    response_model=list[UsageReportMetadata],
)
def fetch_usage_reports(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UsageReportMetadata]:
    """Получение списка всех сгенерированных отчетов по использованию системы.

    Возвращает метаданные всех доступных отчетов, включая информацию
    о периоде, создателе и времени формирования каждого отчета.

    Returns:
        Список метаданных отчетов об использовании системы
    """
    try:
        reports_collection = get_all_usage_reports(db_session=db_session)
        return reports_collection
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Ошибка получения списка отчетов: {error}"
        )
