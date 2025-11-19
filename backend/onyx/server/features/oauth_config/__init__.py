"""OAuth configuration feature module."""

from onyx.server.features.oauth_config.api import admin_router
from onyx.server.features.oauth_config.api import router

__all__ = ["admin_router", "router"]
