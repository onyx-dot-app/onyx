from onyx.configs.app_configs import HOOK_ENABLED
from shared_configs.configs import MULTI_TENANT

# True only when hooks are available: single-tenant deployment with HOOK_ENABLED=true.
HOOKS_AVAILABLE: bool = HOOK_ENABLED and not MULTI_TENANT
