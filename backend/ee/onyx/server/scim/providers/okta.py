"""Okta SCIM provider."""

from __future__ import annotations

from ee.onyx.server.scim.providers.base import ScimProvider


class OktaProvider(ScimProvider):
    """Okta SCIM provider.

    Okta behavioral notes:
      - Uses ``PATCH {"active": false}`` for deprovisioning (not DELETE)
      - Sends path-less PATCH with value dicts containing extra fields
        (``id``, ``schemas``)
      - Expects ``displayName`` and ``groups`` in user responses
      - Only uses ``eq`` operator for ``userName`` filter
    """

    @property
    def name(self) -> str:
        return "okta"

    @property
    def ignored_patch_paths(self) -> frozenset[str]:
        return frozenset({"id", "schemas", "meta"})
