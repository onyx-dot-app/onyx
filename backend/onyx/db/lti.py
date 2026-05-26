from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
from onyx.db.models import UserProject


def build_lti_course_project_description(course_id: str) -> str:
    return f"{LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX}{course_id}"


def get_lti_course_project_for_user(
    project_id: int,
    user_id: UUID,
    db_session: Session,
) -> UserProject | None:
    return (
        db_session.query(UserProject)
        .filter(
            UserProject.id == project_id,
            UserProject.user_id == user_id,
            UserProject.description.startswith(
                LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
            ),
        )
        .one_or_none()
    )
