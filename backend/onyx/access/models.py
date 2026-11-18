from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from onyx.access.utils import (
    prefix_external_group,
    prefix_user_email,
    prefix_user_group,
)
from onyx.configs.constants import PUBLIC_DOC_PAT


class ExternalAccess(BaseModel):
    # arbitrary limit to prevent excessively large permissions sets
    # not internally enforced ... the caller can check this before using the instance
    model_config = ConfigDict(strict=True, frozen=True)

    MAX_NUM_ENTRIES: ClassVar[int] = 5000

    # Emails of external users with access to the doc externally
    external_user_emails: set[StrictStr] = Field(strict=False)
    # Names or external IDs of groups with access to the doc
    external_user_group_ids: set[StrictStr] = Field(strict=False)
    # Whether the document is public in the external system or Onyx
    is_public: bool

    def __str__(self) -> str:
        """Prevent extremely long logs"""

        def truncate_set(s: set[str], max_len: int = 100) -> str:
            s_str = str(s)
            if len(s_str) > max_len:
                return f"{s_str[:max_len]}... ({len(s)} items)"
            return s_str

        return (
            f"ExternalAccess("
            f"external_user_emails={truncate_set(self.external_user_emails)}, "
            f"external_user_group_ids={truncate_set(self.external_user_group_ids)}, "
            f"is_public={self.is_public})"
        )

    @property
    def num_entries(self) -> int:
        return len(self.external_user_emails) + len(self.external_user_group_ids)

    @classmethod
    def public(cls) -> "ExternalAccess":
        return cls(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    @classmethod
    def empty(cls) -> "ExternalAccess":
        """
        A helper function that returns an *empty* set of external user-emails and group-ids, and sets `is_public` to `False`.
        This effectively makes the document in question "private" or inaccessible to anyone else.

        This is especially helpful to use when you are performing permission-syncing, and some document's permissions aren't able
        to be determined (for whatever reason). Setting its `ExternalAccess` to "private" is a feasible fallback.
        """

        return cls(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=False,
        )


class DocExternalAccess(BaseModel):
    """
    This is just a class to wrap the external access and the document ID
    together. It's used for syncing document permissions to the document index.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    external_access: ExternalAccess
    # The document ID
    doc_id: str

    def to_dict(self) -> dict:
        return {
            "external_access": {
                "external_user_emails": list(self.external_access.external_user_emails),
                "external_user_group_ids": list(
                    self.external_access.external_user_group_ids
                ),
                "is_public": self.external_access.is_public,
            },
            "doc_id": self.doc_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocExternalAccess":
        external_access = ExternalAccess(
            external_user_emails=set(
                data["external_access"].get("external_user_emails", [])
            ),
            external_user_group_ids=set(
                data["external_access"].get("external_user_group_ids", [])
            ),
            is_public=data["external_access"]["is_public"],
        )
        return cls(
            external_access=external_access,
            doc_id=data["doc_id"],
        )


class NodeExternalAccess(BaseModel):
    """
    Wraps external access with a hierarchy node's raw ID.
    Used for syncing hierarchy node permissions (e.g., folder permissions).
    """

    model_config = ConfigDict(strict=True, frozen=True)

    external_access: ExternalAccess
    # The raw node ID from the source system (e.g., Google Drive folder ID)
    raw_node_id: str
    # The source type (e.g., "google_drive")
    source: str

    def to_dict(self) -> dict:
        return {
            "external_access": {
                "external_user_emails": list(self.external_access.external_user_emails),
                "external_user_group_ids": list(
                    self.external_access.external_user_group_ids
                ),
                "is_public": self.external_access.is_public,
            },
            "raw_node_id": self.raw_node_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NodeExternalAccess":
        external_access = ExternalAccess(
            external_user_emails=set(
                data["external_access"].get("external_user_emails", [])
            ),
            external_user_group_ids=set(
                data["external_access"].get("external_user_group_ids", [])
            ),
            is_public=data["external_access"]["is_public"],
        )
        return cls(
            external_access=external_access,
            raw_node_id=data["raw_node_id"],
            source=data["source"],
        )


# Union type for elements that can have permissions synced
ElementExternalAccess = DocExternalAccess | NodeExternalAccess


class DocumentAccess(ExternalAccess):
    # User emails for Onyx users, None indicates admin
    user_emails: set[str | None]

    # Names of user groups associated with this document
    user_groups: set[str]

    external_user_emails: set[str]
    external_user_group_ids: set[str]
    is_public: bool

    def __init__(self) -> None:
        raise TypeError(
            "Use `DocumentAccess.build(...)` instead of creating an instance directly."
        )

    def to_acl(self) -> set[str]:
        """Converts the access state to a set of formatted ACL strings.

        NOTE: When querying for documents, the supplied ACL filter strings must
        be formatted in the same way as this function.
        """
        acl_set: set[str] = set()
        for user_email in self.user_emails:
            if user_email:
                acl_set.add(prefix_user_email(user_email))

        for group_name in self.user_groups:
            acl_set.add(prefix_user_group(group_name))

        for external_user_email in self.external_user_emails:
            acl_set.add(prefix_user_email(external_user_email))

        for external_group_id in self.external_user_group_ids:
            acl_set.add(prefix_external_group(external_group_id))

        if self.is_public:
            acl_set.add(PUBLIC_DOC_PAT)

        return acl_set

    @classmethod
    def build(
        cls,
        user_emails: list[str | None],
        user_groups: list[str],
        external_user_emails: list[str],
        external_user_group_ids: list[str],
        is_public: bool,
    ) -> "DocumentAccess":
        """Don't prefix incoming data wth acl type, prefix on read from to_acl!"""

        return cls.model_construct(
            user_emails={email for email in user_emails if email},
            user_groups=set(user_groups),
            external_user_emails=set(external_user_emails),
            external_user_group_ids=set(external_user_group_ids),
            is_public=is_public,
        )


default_public_access = DocumentAccess.build(
    external_user_emails=[],
    external_user_group_ids=[],
    user_emails=[],
    user_groups=[],
    is_public=True,
)
