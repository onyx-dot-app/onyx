import asyncio
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from functools import wraps
from typing import Any
from typing import cast
from typing import TypeVar

import torch

from model_server.constants import GPUStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

F = TypeVar("F", bound=Callable)
FG = TypeVar("FG", bound=Callable[..., Generator | Iterator])


def simple_log_function_time(
    func_name: str | None = None,
    debug_only: bool = False,
    include_args: bool = False,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def wrapped_async_func(*args: Any, **kwargs: Any) -> Any:
                start_time = time.time()
                result = await func(*args, **kwargs)
                elapsed_time_str = str(time.time() - start_time)
                log_name = func_name or func.__name__
                args_str = f" args={args} kwargs={kwargs}" if include_args else ""
                final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds"
                if debug_only:
                    logger.debug(final_log)
                else:
                    logger.notice(final_log)
                return result

            return cast(F, wrapped_async_func)
        else:

            @wraps(func)
            def wrapped_sync_func(*args: Any, **kwargs: Any) -> Any:
                start_time = time.time()
                result = func(*args, **kwargs)
                elapsed_time_str = str(time.time() - start_time)
                log_name = func_name or func.__name__
                args_str = f" args={args} kwargs={kwargs}" if include_args else ""
                final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds"
                if debug_only:
                    logger.debug(final_log)
                else:
                    logger.notice(final_log)
                return result

            return cast(F, wrapped_sync_func)

    return decorator


def get_gpu_type() -> str:
    if torch.cuda.is_available():
        return GPUStatus.CUDA
    if torch.backends.mps.is_available():
        return GPUStatus.MAC_MPS

    return GPUStatus.NONE


def pass_aws_key(api_key: str) -> tuple[str, str, str]:
    if api_key.startswith("aws"):
        try:
            # Example of splitting AWS keys (assuming format like "aws_ACCESSKEY_SECRETKEY_REGION")
            parts = api_key.split("_")
            if len(parts) == 4:
                aws_access_key_id = parts[1]
                aws_secret_access_key = parts[2]
                aws_region = parts[3]
                return aws_access_key_id, aws_secret_access_key, aws_region
            else:
                raise f"Invalid AWS key format for key must be 'aws_ACCESSKEY_SECRETKEY_REGION' but got {parts}"
        except Exception as e:
            raise f"Error parsing AWS key: {e}"

    # Return the API key as-is if it's not an AWS key
    raise "API key does not match expected format format for key must be 'aws_ACCESSKEY_SECRETKEY_REGION'"
