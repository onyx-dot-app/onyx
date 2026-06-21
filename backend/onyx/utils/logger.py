import contextvars
import logging
import os
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from typing import Any

from onyx.utils.platform_utils import is_running_in_container
from onyx.utils.tenant import get_tenant_id_short_string
from shared_configs.configs import DEV_LOGGING_ENABLED
from shared_configs.configs import JSON_LOGGING
from shared_configs.configs import LOG_FILE_NAME
from shared_configs.configs import LOG_LEVEL
from shared_configs.configs import LOG_TO_FILE
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import SLACK_CHANNEL_ID
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import INDEX_ATTEMPT_INFO_CONTEXTVAR
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

logging.addLevelName(logging.INFO + 5, "NOTICE")

pruning_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "pruning_ctx", default=dict()
)

doc_permission_sync_ctx: contextvars.ContextVar[dict[str, Any]] = (
    contextvars.ContextVar("doc_permission_sync_ctx", default=dict())
)


class LoggerContextVars:
    @staticmethod
    def reset() -> None:
        pruning_ctx.set(dict())
        doc_permission_sync_ctx.set(dict())


def get_log_level_from_str(log_level_str: str = LOG_LEVEL) -> int:
    log_level_dict = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "NOTICE": logging.getLevelName("NOTICE"),
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }

    return log_level_dict.get(log_level_str.upper(), logging.INFO)


class OnyxRequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

        record.request_id = ONYX_REQUEST_ID_CONTEXTVAR.get() or "-"
        return True


class OnyxLoggingAdapter(logging.LoggerAdapter):
    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        # In JSON mode, emit context as discrete structured fields instead of
        # prefixing the message string, so they can be queried by log aggregators.
        if JSON_LOGGING:
            return self._inject_context_fields(msg, kwargs)

        # If this is an indexing job, add the attempt ID to the log message
        # This helps filter the logs for this specific indexing
        while True:
            pruning_ctx_dict = pruning_ctx.get()
            if len(pruning_ctx_dict) > 0:
                if "request_id" in pruning_ctx_dict:
                    msg = f"[Prune: {pruning_ctx_dict['request_id']}] {msg}"

                if "cc_pair_id" in pruning_ctx_dict:
                    msg = f"[CC Pair: {pruning_ctx_dict['cc_pair_id']}] {msg}"
                break

            doc_permission_sync_ctx_dict = doc_permission_sync_ctx.get()
            if len(doc_permission_sync_ctx_dict) > 0:
                if "request_id" in doc_permission_sync_ctx_dict:
                    msg = f"[Doc Permissions Sync: {doc_permission_sync_ctx_dict['request_id']}] {msg}"
                break

            index_attempt_info = INDEX_ATTEMPT_INFO_CONTEXTVAR.get()
            if index_attempt_info:
                cc_pair_id, index_attempt_id = index_attempt_info
                msg = (
                    f"[Index Attempt: {index_attempt_id}] [CC Pair: {cc_pair_id}] {msg}"
                )

            break

        # Add tenant information if it differs from default
        # This will always be the case for authenticated API requests
        if MULTI_TENANT:
            tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
            if tenant_id != POSTGRES_DEFAULT_SCHEMA and tenant_id is not None:
                # Get a short string representation of the tenant id for cleaner
                # logs.
                short_tenant = get_tenant_id_short_string(tenant_id)
                msg = f"[t:{short_tenant}] {msg}"

        # request id within a fastapi route
        fastapi_request_id = ONYX_REQUEST_ID_CONTEXTVAR.get()
        if fastapi_request_id:
            msg = f"[{fastapi_request_id}] {msg}"

        # For Slack Bot, logs the channel relevant to the request
        channel_id = self.extra.get(SLACK_CHANNEL_ID) if self.extra else None
        if channel_id:
            msg = f"[Channel ID: {channel_id}] {msg}"

        return msg, kwargs

    def _inject_context_fields(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        """JSON mode counterpart to the message-prefixing in ``process``: collect
        the same contextual values and attach them as structured record fields
        (via ``extra``) so the JSON formatter promotes them to top-level keys."""
        fields: dict[str, Any] = {}

        # Mutually exclusive context groups, mirroring the text-prefix branches.
        pruning_ctx_dict = pruning_ctx.get()
        doc_permission_sync_ctx_dict = doc_permission_sync_ctx.get()
        if pruning_ctx_dict:
            if "request_id" in pruning_ctx_dict:
                fields["prune_request_id"] = pruning_ctx_dict["request_id"]
            if "cc_pair_id" in pruning_ctx_dict:
                fields["cc_pair_id"] = pruning_ctx_dict["cc_pair_id"]
        elif doc_permission_sync_ctx_dict:
            if "request_id" in doc_permission_sync_ctx_dict:
                fields["doc_permission_sync_request_id"] = doc_permission_sync_ctx_dict[
                    "request_id"
                ]
            if "cc_pair_id" in doc_permission_sync_ctx_dict:
                fields["cc_pair_id"] = doc_permission_sync_ctx_dict["cc_pair_id"]
        else:
            index_attempt_info = INDEX_ATTEMPT_INFO_CONTEXTVAR.get()
            if index_attempt_info:
                cc_pair_id, index_attempt_id = index_attempt_info
                fields["index_attempt_id"] = index_attempt_id
                fields["cc_pair_id"] = cc_pair_id

        if MULTI_TENANT:
            tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
            if tenant_id != POSTGRES_DEFAULT_SCHEMA and tenant_id is not None:
                fields["tenant_id"] = get_tenant_id_short_string(tenant_id)

        fastapi_request_id = ONYX_REQUEST_ID_CONTEXTVAR.get()
        if fastapi_request_id:
            fields["request_id"] = fastapi_request_id

        channel_id = self.extra.get(SLACK_CHANNEL_ID) if self.extra else None
        if channel_id:
            fields["slack_channel_id"] = channel_id

        if fields:
            # A caller may pass extra=None explicitly; normalize to a dict
            # before merging so we never call .setdefault() on None.
            extra = kwargs.get("extra")
            if not isinstance(extra, dict):
                extra = {}
                kwargs["extra"] = extra
            # An explicit extra passed by the caller wins over injected context.
            for key, value in fields.items():
                extra.setdefault(key, value)

        return msg, kwargs

    def notice(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        # Stacklevel is set to 2 to point to the actual caller of notice instead of here
        self.log(
            logging.getLevelName("NOTICE"), str(msg), *args, **kwargs, stacklevel=2
        )


class PlainFormatter(logging.Formatter):
    """Adds log levels."""

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        level_display = f"{levelname}:"
        formatted_message = super().format(record)
        return f"{level_display.ljust(9)} {formatted_message}"


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log levels."""

    COLORS = {
        "CRITICAL": "\033[91m",  # Red
        "ERROR": "\033[91m",  # Red
        "WARNING": "\033[93m",  # Yellow
        "NOTICE": "\033[94m",  # Blue
        "INFO": "\033[92m",  # Green
        "DEBUG": "\033[96m",  # Light Green
        "NOTSET": "\033[91m",  # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        if levelname in self.COLORS:
            prefix = self.COLORS[levelname]
            suffix = "\033[0m"
            formatted_message = super().format(record)
            # Ensure the levelname with colon is 9 characters long
            # accounts for the extra characters for coloring
            level_display = f"{prefix}{levelname}{suffix}:"
            return f"{level_display.ljust(18)} {formatted_message}"
        return super().format(record)


def get_json_formatter() -> logging.Formatter:
    """Returns a structured single-line JSON formatter. Standard record
    attributes are emitted as fields and any ``extra`` keys are merged in.

    The ``pythonjsonlogger`` import is deferred to this call site (only reached
    when ``LOG_FORMAT=json``) so that importing this module never hard-fails in
    environments where the optional dependency is absent."""
    from pythonjsonlogger.json import JsonFormatter

    return JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def get_uvicorn_standard_formatter() -> logging.Formatter:
    """Returns the configured uvicorn access-log formatter (JSON or colored text)."""
    if JSON_LOGGING:
        return get_json_formatter()
    return ColoredFormatter(
        "%(asctime)s %(filename)30s %(lineno)4s: [%(request_id)s] %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )


def get_standard_formatter() -> logging.Formatter:
    """Returns the configured standard formatter (JSON or colored text)."""
    if JSON_LOGGING:
        return get_json_formatter()
    return ColoredFormatter(
        "%(asctime)s %(filename)30s %(lineno)4s: %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )


def _add_file_handlers(logger: logging.Logger, formatter: logging.Formatter) -> None:
    # Opt-out via LOG_TO_FILE: pods that can't write log files (e.g. read-only-root
    # containers) set it false and rely on the stdout handler.
    if not LOG_TO_FILE:
        return

    is_containerized = is_running_in_container()
    if not LOG_FILE_NAME or not (is_containerized or DEV_LOGGING_ENABLED):
        return

    for level in ["debug", "info", "notice"]:
        file_name = (
            f"/var/log/onyx/{LOG_FILE_NAME}_{level}.log"
            if is_containerized
            else f"./log/{LOG_FILE_NAME}_{level}.log"
        )
        # Ensure the log directory exists
        log_dir = os.path.dirname(file_name)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        # Truncate log file if DEV_LOGGING_ENABLED (for clean dev experience)
        if DEV_LOGGING_ENABLED and os.path.exists(file_name):
            try:
                open(file_name, "w").close()  # Truncate the file
            except Exception:
                pass  # Ignore errors, just proceed with normal logging

        file_handler = RotatingFileHandler(
            file_name,
            maxBytes=25 * 1024 * 1024,  # 25 MB
            backupCount=5,  # Keep 5 backup files
        )
        file_handler.setLevel(get_log_level_from_str(level))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def setup_logger(
    name: str = __name__,
    log_level: int = get_log_level_from_str(),
    extra: MutableMapping[str, Any] | None = None,
    propagate: bool = True,
) -> OnyxLoggingAdapter:
    logger = logging.getLogger(name)

    # If the logger already has handlers, assume it was already configured and return it.
    if logger.handlers:
        return OnyxLoggingAdapter(logger, extra=extra)

    logger.setLevel(log_level)

    formatter = get_standard_formatter()

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    _add_file_handlers(logger, formatter)

    logger.notice = (  # type: ignore
        lambda msg, *args, **kwargs: logger.log(
            logging.getLevelName("NOTICE"), msg, *args, **kwargs
        )
    )

    # After handler configuration, disable propagation to avoid duplicate logs
    # Prevent messages from propagating to the root logger which can cause
    # duplicate log entries when the root logger is also configured with its
    # own handler (e.g. by Uvicorn / Celery).
    logger.propagate = propagate

    return OnyxLoggingAdapter(logger, extra=extra)


def setup_uvicorn_logger(
    log_level: int = get_log_level_from_str(),
    shared_file_handlers: list[logging.FileHandler] | None = None,
) -> None:
    uvicorn_logger = logging.getLogger("uvicorn.access")
    if not uvicorn_logger:
        return

    formatter = get_uvicorn_standard_formatter()

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    uvicorn_logger.handlers = []
    uvicorn_logger.addHandler(handler)
    uvicorn_logger.setLevel(log_level)
    uvicorn_logger.addFilter(OnyxRequestIDFilter())

    if shared_file_handlers:
        for fh in shared_file_handlers:
            uvicorn_logger.addHandler(fh)

    return


def print_loggers() -> None:
    """Print information about all loggers. Use to debug logging issues."""
    root_logger = logging.getLogger()
    loggers: list[logging.Logger | logging.PlaceHolder] = [root_logger]
    loggers.extend(logging.Logger.manager.loggerDict.values())

    for logger in loggers:
        if isinstance(logger, logging.PlaceHolder):
            # Skip placeholders that aren't actual loggers
            continue

        print(f"Logger: '{logger.name}' (Level: {logging.getLevelName(logger.level)})")
        if logger.handlers:
            for handler in logger.handlers:
                print(f"  Handler: {handler}")
        else:
            print("  No handlers")

        print(f"  Propagate: {logger.propagate}")
        print()


def format_error_for_logging(e: Exception) -> str:
    """Clean error message by removing newlines for better logging."""
    return str(e).replace("\n", " ")
