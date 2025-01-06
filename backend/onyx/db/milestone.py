from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from onyx.configs.constants import MilestoneRecordType
from onyx.db.models import Milestone
from onyx.db.models import User


USER_ASSISTANT_PREFIX = "user_assistants_used_"
MULTI_ASSISTANT_USED = "multi_assistant_used"


def create_milestone(
    user: User | None,
    event_type: MilestoneRecordType,
    db_session: Session,
) -> Milestone:
    milestone = Milestone(
        event_type=event_type,
        user_id=user.id if user else None,
    )
    db_session.add(milestone)
    db_session.commit()

    return milestone


def create_milestone_if_not_exists(
    user: User | None, event_type: MilestoneRecordType, db_session: Session
) -> tuple[Milestone, bool]:
    # Check if it exists
    milestone = db_session.execute(
        select(Milestone).where(Milestone.event_type == event_type)
    ).scalar_one_or_none()

    if milestone is not None:
        return milestone, False

    # If it doesn't exist, try to create it.
    try:
        milestone = create_milestone(user, event_type, db_session)
        return milestone, True
    except IntegrityError:
        # Another thread or process inserted it in the meantime
        db_session.rollback()
        # Fetch again to return the existing record
        milestone = db_session.execute(
            select(Milestone).where(Milestone.event_type == event_type)
        ).scalar_one()  # Now should exist
        return milestone, False


def update_user_assistant_milestone(
    milestone: Milestone,
    user_id: str | None,
    assistant_id: int,
    db_session: Session,
) -> None:
    event_tracker = milestone.event_tracker
    if event_tracker is None:
        milestone.event_tracker = event_tracker = {}

    if event_tracker.get(MULTI_ASSISTANT_USED):
        # No need to keep tracking and populating if the milestone has already been hit
        return

    user_key = f"{USER_ASSISTANT_PREFIX}{user_id}"

    if event_tracker.get(user_key) is None:
        event_tracker[user_key] = [assistant_id]
    elif assistant_id not in event_tracker[user_key]:
        event_tracker[user_key].append(assistant_id)

    flag_modified(milestone, "event_tracker")
    db_session.commit()


def check_multi_assistant_milestone(
    milestone: Milestone,
    db_session: Session,
) -> tuple[bool, bool]:
    """Returns if the milestone was hit and if it was just hit for the first time"""
    event_tracker = milestone.event_tracker
    if event_tracker is None:
        return False, False

    if event_tracker.get(MULTI_ASSISTANT_USED):
        return True, False

    for key, value in event_tracker.items():
        if key.startswith(USER_ASSISTANT_PREFIX) and len(value) > 1:
            event_tracker[MULTI_ASSISTANT_USED] = True
            flag_modified(milestone, "event_tracker")
            db_session.commit()
            return True, True

    return False, False
