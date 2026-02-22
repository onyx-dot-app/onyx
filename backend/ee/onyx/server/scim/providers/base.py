"""Base SCIM provider abstraction."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from uuid import UUID

from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimUserGroupRef
from ee.onyx.server.scim.models import ScimUserResource
from onyx.db.models import User
from onyx.db.models import UserGroup


class ScimProvider(ABC):
    """Base class for provider-specific SCIM behavior.

    Subclass this to handle IdP-specific quirks. The base class provides
    RFC 7643-compliant response builders that populate all standard fields.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g. ``"okta"``)."""
        ...

    @property
    @abstractmethod
    def ignored_patch_paths(self) -> frozenset[str]:
        """SCIM attribute paths to silently skip in PATCH value-object dicts.

        IdPs may include read-only or meta fields alongside actual changes
        (e.g. Okta sends ``{"id": "...", "active": false}``). Paths listed
        here are silently dropped instead of raising an error.
        """
        ...

    def build_user_resource(
        self,
        user: User,
        external_id: str | None = None,
        groups: list[tuple[int, str]] | None = None,
        scim_username: str | None = None,
    ) -> ScimUserResource:
        """Build a SCIM User response from an Onyx User.

        Args:
            user: The Onyx user model.
            external_id: The IdP's external identifier for this user.
            groups: List of ``(group_id, group_name)`` tuples for the
                ``groups`` read-only attribute. Pass ``None`` or ``[]``
                for newly-created users.
            scim_username: The original-case userName from the IdP. Falls
                back to ``user.email`` (lowercase) when not available.
        """
        group_refs = [
            ScimUserGroupRef(value=str(gid), display=gname)
            for gid, gname in (groups or [])
        ]

        # Use original-case userName if stored, otherwise fall back to the
        # lowercased email from the User model.
        username = scim_username or user.email

        return ScimUserResource(
            id=str(user.id),
            externalId=external_id,
            userName=username,
            name=self._build_scim_name(user),
            displayName=user.personal_name,
            emails=[ScimEmail(value=username, type="work", primary=True)],
            active=user.is_active,
            groups=group_refs,
            meta=ScimMeta(resourceType="User"),
        )

    def build_group_resource(
        self,
        group: UserGroup,
        members: list[tuple[UUID, str | None]],
        external_id: str | None = None,
    ) -> ScimGroupResource:
        """Build a SCIM Group response from an Onyx UserGroup."""
        scim_members = [
            ScimGroupMember(value=str(uid), display=email) for uid, email in members
        ]
        return ScimGroupResource(
            id=str(group.id),
            externalId=external_id,
            displayName=group.name,
            members=scim_members,
            meta=ScimMeta(resourceType="Group"),
        )

    @staticmethod
    def _build_scim_name(user: User) -> ScimName | None:
        """Extract SCIM name components from a user's personal name."""
        if not user.personal_name:
            return None
        parts = user.personal_name.split(" ", 1)
        return ScimName(
            givenName=parts[0],
            familyName=parts[1] if len(parts) > 1 else None,
            formatted=user.personal_name,
        )


def get_default_provider() -> ScimProvider:
    """Return the default SCIM provider.

    Currently returns ``OktaProvider`` since Okta is the primary supported
    IdP. When provider detection is added (via token metadata or tenant
    config), this can be replaced with dynamic resolution.
    """
    from ee.onyx.server.scim.providers.okta import OktaProvider

    return OktaProvider()
