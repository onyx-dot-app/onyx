"""Entra ID (Azure AD) SCIM provider."""

from __future__ import annotations

from ee.onyx.server.scim.models import SCIM_ENTERPRISE_USER_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.providers.base import COMMON_IGNORED_PATCH_PATHS
from ee.onyx.server.scim.providers.base import ScimProvider

_ENTRA_IGNORED_PATCH_PATHS = COMMON_IGNORED_PATCH_PATHS


class EntraProvider(ScimProvider):
    """Entra ID (Azure AD) SCIM provider.

    Entra behavioral notes:
      - Sends capitalized PATCH ops (``"Add"``, ``"Replace"``, ``"Remove"``)
        — handled by ``ScimPatchOperation.normalize_op`` validator.
      - Sends the enterprise extension URN as a key in path-less PATCH value
        dicts — handled by ``_set_enterprise_field`` in ``patch.py`` to
        store department/manager values.
      - Expects the enterprise extension schema in ``schemas`` arrays and
        ``/Schemas`` + ``/ResourceTypes`` discovery endpoints.
    """

    @property
    def name(self) -> str:
        return "entra"

    @property
    def ignored_patch_paths(self) -> frozenset[str]:
        return _ENTRA_IGNORED_PATCH_PATHS

    @property
    def user_schemas(self) -> list[str]:
        return [SCIM_USER_SCHEMA, SCIM_ENTERPRISE_USER_SCHEMA]
