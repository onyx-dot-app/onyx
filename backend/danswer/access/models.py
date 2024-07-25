from dataclasses import dataclass
from uuid import UUID

from danswer.access.utils import prefix_user
from danswer.access.utils import prefix_user_group
from danswer.configs.constants import PUBLIC_DOC_PAT


@dataclass(frozen=True)
class DocumentAccess:
    user_ids: set[str]  # stringified UUIDs
    user_groups: set[str]  # names of user groups associated with this document
    is_public: bool

    def to_acl(self) -> list[str]:
        return (
            [prefix_user(user_id) for user_id in self.user_ids]
            + [prefix_user_group(group_name) for group_name in self.user_groups]
            + ([PUBLIC_DOC_PAT] if self.is_public else [])
        )

    @classmethod
    def build(
        cls, user_ids: list[UUID | None], user_groups: list[str], is_public: bool
    ) -> "DocumentAccess":
        return cls(
            user_ids={str(user_id) for user_id in user_ids if user_id},
            user_groups=set(user_groups),
            is_public=is_public,
        )
