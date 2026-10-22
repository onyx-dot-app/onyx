from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class LtiCourseKnowledgeScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    cc_pair_keys: list[tuple[int, int]]
    accessible_node_ids: set[int]


class LtiGoogleDriveOAuthState(BaseModel):
    user_id: str
    course_id: str
    credential_id: int
    tenant_id: str


class LtiGoogleDriveCallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class LtiGoogleDriveCallbackResponse(BaseModel):
    success: bool
