"""Base SCIM provider abstraction."""

from __future__ import annotations

import json
import logging
from abc import ABC
from abc import abstractmethod
from uuid import UUID

from pydantic import ValidationError

from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimMappingFields
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimUserGroupRef
from ee.onyx.server.scim.models import ScimUserResource
from onyx.db.models import User
from onyx.db.models import UserGroup


logger = logging.getLogger(__name__)

COMMON_IGNORED_PATCH_PATHS: frozenset[str] = frozenset(
    {
        "id",
        "schemas",
        "meta",
    }
)


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

    @property
    def user_schemas(self) -> list[str]:
        """Schema URIs to include in User resource responses.

        Override in subclasses to advertise additional schemas (e.g. the
        enterprise extension for Entra ID).
        """
        return [SCIM_USER_SCHEMA]

    def build_user_resource(
        self,
        user: User,
        external_id: str | None = None,
        groups: list[tuple[int, str]] | None = None,
        scim_username: str | None = None,
        fields: ScimMappingFields | None = None,
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
            fields: Stored mapping fields that the IdP expects round-tripped.
        """
        f = fields or ScimMappingFields()
        group_refs = [
            ScimUserGroupRef(value=str(gid), display=gname)
            for gid, gname in (groups or [])
        ]

        username = scim_username or user.email

        name = self.build_scim_name(user, f)
        emails = _deserialize_emails(f.scim_emails_json, username)

        return ScimUserResource(
            schemas=list(self.user_schemas),
            id=str(user.id),
            externalId=external_id,
            userName=username,
            name=name,
            displayName=user.personal_name,
            emails=emails,
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

    def build_scim_name(
        self,
        user: User,
        fields: ScimMappingFields,
    ) -> ScimName | None:
        """Build SCIM name components for the response.

        Round-trips stored ``given_name``/``family_name`` when available (so
        the IdP gets back what it sent). Falls back to splitting
        ``personal_name`` for users provisioned before we stored components.
        Providers may override for custom behavior.
        """
        if fields.given_name is not None or fields.family_name is not None:
            return ScimName(
                givenName=fields.given_name,
                familyName=fields.family_name,
                formatted=user.personal_name,
            )
        if not user.personal_name:
            return None
        parts = user.personal_name.split(" ", 1)
        return ScimName(
            givenName=parts[0],
            familyName=parts[1] if len(parts) > 1 else None,
            formatted=user.personal_name,
        )


def _deserialize_emails(stored_json: str | None, username: str) -> list[ScimEmail]:
    """Deserialize stored email entries or build a default work email."""
    if stored_json:
        try:
            entries = json.loads(stored_json)
            if isinstance(entries, list) and entries:
                return [ScimEmail(**e) for e in entries]
        except (json.JSONDecodeError, TypeError, ValidationError):
            logger.warning(
                "Corrupt scim_emails_json, falling back to default: %s", stored_json
            )
    return [ScimEmail(value=username, type="work", primary=True)]


def serialize_emails(emails: list[ScimEmail]) -> str | None:
    """Serialize SCIM email entries to JSON for storage."""
    if not emails:
        return None
    return json.dumps([e.model_dump(exclude_none=True) for e in emails])


def get_default_provider() -> ScimProvider:
    """Return the default SCIM provider.

    Currently returns ``OktaProvider`` since Okta is the primary supported
    IdP. When provider detection is added (via token metadata or tenant
    config), this can be replaced with dynamic resolution.
    """
    from ee.onyx.server.scim.providers.okta import OktaProvider

    return OktaProvider()
