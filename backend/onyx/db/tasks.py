from datetime import datetime, timedelta

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import delete

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.models import TaskQueueState, TaskStatus


def claim_task_with_id(db_session: Session, task_id: str) -> bool:
    """Only one worker can claim a pending job. Terminal jobs stay terminal."""
    claimed = db_session.scalar(
        update(TaskQueueState)
        .where(
            TaskQueueState.task_id == task_id,
            TaskQueueState.status == TaskStatus.PENDING,
        )
        .values(status=TaskStatus.STARTED, start_time=func.now())
        .returning(TaskQueueState.id)
    )
    db_session.commit()
    return claimed is not None


def get_started_task_for_update(
    db_session: Session, task_id: str
) -> TaskQueueState | None:
    return db_session.scalar(
        select(TaskQueueState)
        .where(
            TaskQueueState.task_id == task_id,
            TaskQueueState.status == TaskStatus.STARTED,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def fail_started_task(db_session: Session, task_id: str) -> None:
    db_session.rollback()
    db_session.execute(
        update(TaskQueueState)
        .where(
            TaskQueueState.task_id == task_id,
            TaskQueueState.status == TaskStatus.STARTED,
        )
        .values(status=TaskStatus.FAILURE, start_time=func.now())
    )
    db_session.commit()


def cleanup_stale_tasks(
    db_session: Session,
    task_name_prefix: str,
    pending_timeout: int,
    started_timeout: int,
) -> None:
    """Retain failures for a day, including jobs whose worker never ran."""
    matching = TaskQueueState.task_name.startswith(
        f"{task_name_prefix}_", autoescape=True
    )
    db_session.execute(
        delete(TaskQueueState).where(
            matching,
            or_(
                TaskQueueState.status == TaskStatus.SUCCESS,
                and_(
                    TaskQueueState.status == TaskStatus.FAILURE,
                    func.coalesce(
                        TaskQueueState.start_time, TaskQueueState.register_time
                    )
                    < func.now() - timedelta(days=1),
                ),
            ),
        )
    )
    db_session.execute(
        update(TaskQueueState)
        .where(
            matching,
            or_(
                and_(
                    TaskQueueState.status == TaskStatus.PENDING,
                    TaskQueueState.register_time
                    < func.now() - timedelta(seconds=pending_timeout),
                ),
                and_(
                    TaskQueueState.status == TaskStatus.STARTED,
                    func.coalesce(
                        TaskQueueState.start_time, TaskQueueState.register_time
                    )
                    < func.now() - timedelta(seconds=started_timeout),
                ),
            ),
        )
        .values(status=TaskStatus.FAILURE, start_time=func.now())
    )
    db_session.commit()


def get_latest_task(
    task_name: str,
    db_session: Session,
) -> TaskQueueState | None:
    stmt = (
        select(TaskQueueState)
        .where(TaskQueueState.task_name == task_name)
        .order_by(desc(TaskQueueState.id))
        .limit(1)
    )

    result = db_session.execute(stmt)
    latest_task = result.scalars().first()

    return latest_task


def get_latest_task_by_type(
    task_name: str,
    db_session: Session,
) -> TaskQueueState | None:
    stmt = (
        select(TaskQueueState)
        .where(TaskQueueState.task_name.like(f"%{task_name}%"))
        .order_by(desc(TaskQueueState.id))
        .limit(1)
    )

    result = db_session.execute(stmt)
    latest_task = result.scalars().first()

    return latest_task


def register_task(
    task_name: str,
    db_session: Session,
    task_id: str = "",
    status: TaskStatus = TaskStatus.PENDING,
    start_time: datetime | None = None,
) -> TaskQueueState:
    new_task = TaskQueueState(
        task_id=task_id,
        task_name=task_name,
        status=status,
        start_time=start_time,
    )

    db_session.add(new_task)
    db_session.commit()

    return new_task


def get_task_with_id(
    db_session: Session,
    task_id: str,
) -> TaskQueueState | None:
    return db_session.scalar(
        select(TaskQueueState).where(TaskQueueState.task_id == task_id)
    )


def delete_task_with_id(
    db_session: Session,
    task_id: str,
) -> None:
    db_session.execute(delete(TaskQueueState).where(TaskQueueState.task_id == task_id))
    db_session.commit()


def get_all_tasks_with_prefix(
    db_session: Session, task_name_prefix: str
) -> list[TaskQueueState]:
    return list(
        db_session.scalars(
            select(TaskQueueState).where(
                TaskQueueState.task_name.like(f"{task_name_prefix}_%")
            )
        )
    )


def mark_task_as_started_with_id(
    db_session: Session,
    task_id: str,
) -> None:
    task = get_task_with_id(db_session=db_session, task_id=task_id)
    if not task:
        raise RuntimeError(f"A task with the task-id {task_id=} does not exist")

    task.status = TaskStatus.STARTED
    db_session.commit()


def mark_task_as_finished_with_id(
    db_session: Session,
    task_id: str,
    success: bool = True,
) -> None:
    task = get_task_with_id(db_session=db_session, task_id=task_id)
    if not task:
        raise RuntimeError(f"A task with the task-id {task_id=} does not exist")

    task.status = TaskStatus.SUCCESS if success else TaskStatus.FAILURE
    db_session.commit()


def mark_task_start(
    task_name: str,
    db_session: Session,
) -> None:
    task = get_latest_task(task_name, db_session)
    if not task:
        raise ValueError(f"No task found with name {task_name}")

    task.start_time = func.now()
    db_session.commit()


def mark_task_finished(
    task_name: str,
    db_session: Session,
    success: bool = True,
) -> None:
    latest_task = get_latest_task(task_name, db_session)
    if latest_task is None:
        raise ValueError(f"tasks for {task_name} do not exist")

    latest_task.status = TaskStatus.SUCCESS if success else TaskStatus.FAILURE
    db_session.commit()


def check_task_is_live_and_not_timed_out(
    task: TaskQueueState,
    db_session: Session,
    timeout: int = JOB_TIMEOUT,
) -> bool:
    # We only care for live tasks to not create new periodic tasks
    if task.status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]:
        return False

    current_db_time = get_db_current_time(db_session=db_session)

    last_update_time = task.register_time
    if task.start_time:
        last_update_time = max(task.register_time, task.start_time)

    time_elapsed = current_db_time - last_update_time
    return time_elapsed.total_seconds() < timeout
