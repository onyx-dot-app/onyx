from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.db.engine import get_db_current_time
from danswer.db.models import TaskQueueState
from danswer.db.models import TaskStatus


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
    task_id: str,
    task_name: str,
    db_session: Session,
) -> TaskQueueState:
    new_task = TaskQueueState(
        task_id=task_id, task_name=task_name, status=TaskStatus.PENDING
    )

    db_session.add(new_task)
    db_session.commit()

    return new_task


def mark_task_start(
    task_name: str,
    db_session: Session,
) -> None:
    task = get_latest_task(task_name, db_session)
    if not task:
        raise ValueError(f"No task found with name {task_name}")

    task.start_time = func.now()  # type: ignore
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
