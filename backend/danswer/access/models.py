from dataclasses import dataclass

from danswer.access.utils import prefix_external_group
from danswer.access.utils import prefix_user_email
from danswer.access.utils import prefix_user_group
from danswer.configs.constants import PUBLIC_DOC_PAT


@dataclass(frozen=True)
class ExternalAccess:
    # Emails of external users with access to the doc externally
    external_user_emails: set[str]
    # Names or external IDs of groups with access to the doc
    external_user_group_ids: set[str]
    # Whether the document is public in the external system or Danswer
    is_public: bool


@dataclass(frozen=True)
class DocumentAccess(ExternalAccess):
    # User emails for Danswer users, None indicates admin
    user_emails: set[str | None]
    # Names of user groups associated with this document
    user_groups: set[str]

    def to_acl(self) -> set[str]:
        return set(
            [
                prefix_user_email(user_email)
                for user_email in self.user_emails
                if user_email
            ]
            + [prefix_user_group(group_name) for group_name in self.user_groups]
            + [
                prefix_user_email(user_email)
                for user_email in self.external_user_emails
            ]
            + [
                # The group names are already prefixed by the source type
                # This adds an additional prefix of "external_group:"
                prefix_external_group(group_name)
                for group_name in self.external_user_group_ids
            ]
            + ([PUBLIC_DOC_PAT] if self.is_public else [])
        )

    @classmethod
    def build(
        cls,
        user_emails: list[str | None],
        user_groups: list[str],
        external_user_emails: list[str],
        external_user_group_ids: list[str],
        is_public: bool,
    ) -> "DocumentAccess":
        return cls(
            external_user_emails={
                prefix_user_email(external_email)
                for external_email in external_user_emails
            },
            external_user_group_ids={
                prefix_external_group(external_group_id)
                for external_group_id in external_user_group_ids
            },
            user_emails={
                prefix_user_email(user_email)
                for user_email in user_emails
                if user_email
            },
            user_groups=set(user_groups),
            is_public=is_public,
        )


default_public_access = DocumentAccess(
    external_user_emails=set(),
    external_user_group_ids=set(),
    user_emails=set(),
    user_groups=set(),
    is_public=True,
)
