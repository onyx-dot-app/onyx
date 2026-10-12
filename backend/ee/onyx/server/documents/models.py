from pydantic import BaseModel

from ee.onyx.server.user_group.models import MinimalUserGroupSnapshot


class CCPairDataAccessUpdateRequest(BaseModel):
    group_ids: list[int]


class CCPairDataAccess(BaseModel):
    # Only the groups the caller can see.
    groups: list[MinimalUserGroupSnapshot]
