import logging

from celery import current_task

from onyx.utils.logger import ColoredFormatter
from onyx.utils.logger import get_json_formatter
from onyx.utils.logger import PlainFormatter


class CeleryTaskJsonFormatter(logging.Formatter):
    """JSON formatter for celery tasks. Emits ``task_id``/``task_name`` as
    structured fields instead of prefixing the message string."""

    def __init__(self) -> None:
        super().__init__()
        self._json_formatter = get_json_formatter()

    def format(self, record: logging.LogRecord) -> str:
        task = current_task
        if task and task.request:
            record.__dict__.update(task_id=task.request.id, task_name=task.name)
        return self._json_formatter.format(record)


class CeleryTaskPlainFormatter(PlainFormatter):
    def format(self, record: logging.LogRecord) -> str:
        task = current_task
        if task and task.request:
            record.__dict__.update(task_id=task.request.id, task_name=task.name)
            record.msg = f"[{task.name}({task.request.id})] {record.msg}"

        return super().format(record)


class CeleryTaskColoredFormatter(ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        task = current_task
        if task and task.request:
            record.__dict__.update(task_id=task.request.id, task_name=task.name)
            record.msg = f"[{task.name}({task.request.id})] {record.msg}"

        return super().format(record)
