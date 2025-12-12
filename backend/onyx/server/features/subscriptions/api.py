from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.models import UserSubscription
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/subscriptions")


class SubscriptionRequest(BaseModel):
    """Request model for creating a subscription.

    Example: {"text": "subscribe python-updates"}
    The text will be parsed to extract the topic after the word 'subscribe'.
    """
    text: str


class SubscriptionResponse(BaseModel):
    """Response model for subscription operations."""
    id: int
    topic: str
    is_active: bool
    message: str


@router.post("")
def create_subscription(
    request: SubscriptionRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SubscriptionResponse:
    """
    Create a subscription for a user to a specific topic.

    The request text should follow the pattern: "subscribe <topic>"
    For example: "subscribe python-updates" or "subscribe news-alerts"

    If the user is already subscribed to the topic, the subscription will be reactivated.
    """
    # Parse the text to extract the topic
    text = request.text.strip()

    # Check if the text starts with "subscribe"
    if not text.lower().startswith("subscribe"):
        raise HTTPException(
            status_code=400,
            detail="Request must start with 'subscribe'. Example: 'subscribe python-updates'"
        )

    # Extract the topic (everything after "subscribe")
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        raise HTTPException(
            status_code=400,
            detail="No topic specified. Example: 'subscribe python-updates'"
        )

    topic = parts[1].strip()

    # Validate topic (optional: add more validation rules)
    if len(topic) > 255:
        raise HTTPException(
            status_code=400,
            detail="Topic name too long. Maximum 255 characters."
        )

    # Check if subscription already exists
    existing_subscription = db_session.execute(
        select(UserSubscription).where(
            and_(
                UserSubscription.user_id == user.id,
                UserSubscription.topic == topic
            )
        )
    ).scalar_one_or_none()

    if existing_subscription:
        # Reactivate if it was inactive
        if not existing_subscription.is_active:
            existing_subscription.is_active = True
            db_session.commit()
            logger.info(f"Reactivated subscription for user {user.id} to topic '{topic}'")
            return SubscriptionResponse(
                id=existing_subscription.id,
                topic=topic,
                is_active=True,
                message=f"Successfully reactivated subscription to '{topic}'"
            )
        else:
            logger.info(f"User {user.id} already subscribed to topic '{topic}'")
            return SubscriptionResponse(
                id=existing_subscription.id,
                topic=topic,
                is_active=True,
                message=f"Already subscribed to '{topic}'"
            )

    # Create new subscription
    new_subscription = UserSubscription(
        user_id=user.id,
        topic=topic,
        is_active=True
    )

    db_session.add(new_subscription)
    db_session.commit()
    db_session.refresh(new_subscription)

    logger.info(f"Created subscription for user {user.id} to topic '{topic}'")

    return SubscriptionResponse(
        id=new_subscription.id,
        topic=topic,
        is_active=True,
        message=f"Successfully subscribed to '{topic}'"
    )


@router.get("")
def get_subscriptions(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[SubscriptionResponse]:
    """Get all active subscriptions for the current user."""
    subscriptions = db_session.execute(
        select(UserSubscription).where(
            and_(
                UserSubscription.user_id == user.id,
                UserSubscription.is_active == True
            )
        )
    ).scalars().all()

    return [
        SubscriptionResponse(
            id=sub.id,
            topic=sub.topic,
            is_active=sub.is_active,
            message=""
        )
        for sub in subscriptions
    ]


@router.delete("/{subscription_id}")
def unsubscribe(
    subscription_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SubscriptionResponse:
    """Unsubscribe from a topic by subscription ID."""
    subscription = db_session.execute(
        select(UserSubscription).where(
            and_(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == user.id
            )
        )
    ).scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="Subscription not found"
        )

    # Mark as inactive instead of deleting
    subscription.is_active = False
    db_session.commit()

    logger.info(f"User {user.id} unsubscribed from topic '{subscription.topic}'")

    return SubscriptionResponse(
        id=subscription.id,
        topic=subscription.topic,
        is_active=False,
        message=f"Successfully unsubscribed from '{subscription.topic}'"
    )
