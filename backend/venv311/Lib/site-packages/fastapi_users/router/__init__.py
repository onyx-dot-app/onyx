from fastapi_users.router.auth import get_auth_router
from fastapi_users.router.common import ErrorCode
from fastapi_users.router.register import get_register_router
from fastapi_users.router.reset import get_reset_password_router
from fastapi_users.router.users import get_users_router
from fastapi_users.router.verify import get_verify_router

__all__ = [
    "ErrorCode",
    "get_auth_router",
    "get_register_router",
    "get_reset_password_router",
    "get_users_router",
    "get_verify_router",
]

try:  # pragma: no cover
    from fastapi_users.router.oauth import (  # noqa: F401
        get_oauth_associate_router,
        get_oauth_router,
    )

    __all__.append("get_oauth_router")
    __all__.append("get_oauth_associate_router")
except ModuleNotFoundError:  # pragma: no cover
    pass
