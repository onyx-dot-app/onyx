"""
Module for handling chat-related milestone tracking and telemetry.
"""

from sqlalchemy.orm import Session

from onyx.configs.constants import MilestoneRecordType
from onyx.configs.constants import NO_AUTH_USER_ID
from onyx.db.milestone import check_multi_assistant_milestone
from onyx.db.milestone import create_milestone_if_not_exists
from onyx.db.milestone import update_user_assistant_milestone
from onyx.db.models import User
from onyx.utils.telemetry import mt_cloud_telemetry


def process_multi_assistant_milestone(
    user: User | None,
    assistant_id: int,
    tenant_id: str,
    db_session: Session,
) -> None:
    """
    Process the multi-assistant milestone for a user.

    This function:
    1. Creates or retrieves the multi-assistant milestone
    2. Updates the milestone with the current assistant usage
    3. Checks if the milestone was just achieved
    4. Sends telemetry if the milestone was just hit

    Args:
        user: The user for whom to process the milestone (can be None for anonymous users)
        assistant_id: The ID of the assistant being used
        tenant_id: The current tenant ID
        db_session: Database session for queries
    """
    # Create or retrieve the multi-assistant milestone
    multi_assistant_milestone, _is_new = create_milestone_if_not_exists(
        user=user,
        event_type=MilestoneRecordType.MULTIPLE_ASSISTANTS,
        db_session=db_session,
    )

    # Update the milestone with the current assistant usage
    update_user_assistant_milestone(
        milestone=multi_assistant_milestone,
        user_id=str(user.id) if user else NO_AUTH_USER_ID,
        assistant_id=assistant_id,
        db_session=db_session,
    )

    # Check if the milestone was just achieved
    _, just_hit_multi_assistant_milestone = check_multi_assistant_milestone(
        milestone=multi_assistant_milestone,
        db_session=db_session,
    )

    # Send telemetry if the milestone was just hit
    if just_hit_multi_assistant_milestone:
        mt_cloud_telemetry(
            distinct_id=tenant_id,
            event=MilestoneRecordType.MULTIPLE_ASSISTANTS,
            properties=None,
        )
