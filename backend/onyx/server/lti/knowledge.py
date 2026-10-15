from sqlalchemy.orm import Session

from onyx.db.lti_knowledge import validate_lti_course_knowledge_scope
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.lti.utils import get_lti_launch_context
from onyx.server.lti.utils import lti_roles_include_instructor


def require_lti_instructor_launch_context(user: User, course_id: str) -> None:
    launch_context = get_lti_launch_context(get_raw_redis_client(), user.id)
    if launch_context is None:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "No active LTI launch context found for this session",
        )
    if launch_context.course_id != course_id:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "LTI course context does not match this request",
        )
    if not lti_roles_include_instructor(launch_context.roles):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Only instructors can manage course tutor knowledge",
        )


def validate_lti_course_knowledge_selection(
    db_session: Session,
    course_id: str,
    user: User,
    hierarchy_node_ids: list[int],
    document_ids: list[str],
) -> None:
    require_lti_instructor_launch_context(user, course_id)
    validate_lti_course_knowledge_scope(
        db_session=db_session,
        course_id=course_id,
        user=user,
        hierarchy_node_ids=hierarchy_node_ids,
        document_ids=document_ids,
    )
