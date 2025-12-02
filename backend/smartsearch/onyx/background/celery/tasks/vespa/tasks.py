from typing import cast

from redis import Redis
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.db.enums import SyncStatus, SyncType
from onyx.db.sync_record import update_sync_record_status
from onyx.redis.redis_usergroup import RedisUserGroup
from onyx.utils.logger import setup_logger
from smartsearch.onyx.db.user_group import (
    delete_user_group,
    fetch_user_group,
    mark_user_group_as_synced,
    prepare_user_group_for_deletion,
)

logger = setup_logger()


def monitor_usergroup_taskset(
    tenant_id: str,
    key_bytes: bytes,
    r: Redis,
    db_session: Session,
) -> None:
    """Мониторит процесс синхронизации пользовательской
    группы через Redis.

    Эта функция отслеживает выполнение задач синхронизации
    пользовательской группы, используя Redis для координации между воркерами.
    Она обновляет статус синхронизации в БД и выполняет завершающие действия
    по завершении всех задач.

    Основные этапы работы:
    1. Извлечение ID группы из ключа блокировки Redis
    2. Отслеживание выполнения задач через Redis Set
    3. Обновление статуса синхронизации в БД
    4. Завершение операции (синхронизация или удаление)

    Args:
        tenant_id (str): Уникальный идентификатор тенанта
        key_bytes (bytes): Ключ блокировки Redis в байтах
        r (Redis): Клиент Redis для взаимодействия
        db_session (Session): Сессия БД для выполнения операций

    Raises:
        ValueError: Если ID группы не может быть преобразован в целое число
    """
    # Декодируем ключ блокировки для получения fence ключа
    fence_key = key_bytes.decode("utf-8")

    # Извлекаем идентификатор группы из ключа блокировки
    group_id_string = RedisUserGroup.get_id_from_fence_key(key=fence_key)

    if not group_id_string:
        task_logger.warning(f"Не удалось извлечь ID группы из ключа: {fence_key}")
        return

    try:
        user_group_id = int(group_id_string)
    except ValueError:
        error_msg = f"group_id_string ({group_id_string}) не является целым числом!"
        task_logger.exception(error_msg)
        raise

    # Инициализация объекта RedisUserGroup для работы с состоянием группы
    redis_user_group = RedisUserGroup(tenant_id, user_group_id)

    # Проверяем, активирована ли блокировка для группы
    if not redis_user_group.fenced:
        task_logger.debug(f"Блокировка для группы {user_group_id} не активна")
        return

    # Получаем исходное количество задач для синхронизации
    initial_task_count = redis_user_group.payload
    if initial_task_count is None:
        task_logger.warning(
            "Нет данных о количестве задач для группы %s",
            user_group_id,
        )
        return

    # Получаем текущее количество оставшихся задач из Redis Set
    remaining_tasks_count = cast(
        int,
        r.scard(redis_user_group.taskset_key)
    )

    task_logger.info(
        "Прогресс синхронизации группы: "
        "ID=%s, "
        "осталось задач=%s, "
        "начальное количество=%s",
        user_group_id,
        remaining_tasks_count,
        initial_task_count,
    )

    # Если задачи еще выполняются, обновляем статус на "в процессе"
    if remaining_tasks_count > 0:
        update_sync_record_status(
            db_session=db_session,
            entity_id=user_group_id,
            sync_type=SyncType.USER_GROUP,
            sync_status=SyncStatus.IN_PROGRESS,
            num_docs_synced=remaining_tasks_count,
        )
        return

    # Получаем информацию о группе из базы данных
    user_group_data = fetch_user_group(
        db_session=db_session,
        user_group_id=user_group_id
    )

    if not user_group_data:
        task_logger.error(f"Группа с ID {user_group_id} не найдена в БД")
        redis_user_group.reset()
        return

    user_group_name = user_group_data.name
    try:
        # Обработка удаления группы (если она помечена на удаление)
        if user_group_data.is_up_for_deletion:
            # Дополнительная проверка готовности к удалению
            mark_user_group_as_synced(
                db_session=db_session, user_group=user_group_data
            )
            prepare_user_group_for_deletion(
                db_session=db_session, user_group_id=user_group_id
            )
            delete_user_group(
                db_session=db_session, user_group=user_group_data
            )

            # Обновление статуса синхронизации на "успешно"
            update_sync_record_status(
                db_session=db_session,
                entity_id=user_group_id,
                sync_type=SyncType.USER_GROUP,
                sync_status=SyncStatus.SUCCESS,
                num_docs_synced=initial_task_count,
            )

            task_logger.info(
                "Группа успешно удалена: "
                "название=%s, "
                "ID=%s",
                user_group_name,
                user_group_id,
            )

            # Обработка обычной синхронизации группы
        else:
            mark_user_group_as_synced(
                db_session=db_session,
                user_group=user_group_data,
            )

            # Обновление статуса синхронизации
            update_sync_record_status(
                db_session=db_session,
                entity_id=user_group_id,
                sync_type=SyncType.USER_GROUP,
                sync_status=SyncStatus.SUCCESS,
                num_docs_synced=initial_task_count,
            )

            task_logger.info(
                "Группа успешно синхронизирована: "
                "название=%s, "
                "ID=%s",
                user_group_name,
                user_group_id,
            )

    except Exception as error:
        task_logger.error(
            "Ошибка при обработке группы %s (ID: %s): %s",
            user_group_name,
            user_group_id,
            str(error),
        )

        # Обновление статуса на "ошибка" при возникновении исключения
        update_sync_record_status(
            db_session=db_session,
            entity_id=user_group_id,
            sync_type=SyncType.USER_GROUP,
            sync_status=SyncStatus.FAILED,
            num_docs_synced=initial_task_count,
        )

        # Повторно вызываем исключение для обработки на верхнем уровне
        raise error

    finally:
        # Всегда очищаем состояние Redis после обработки
        redis_user_group.reset()