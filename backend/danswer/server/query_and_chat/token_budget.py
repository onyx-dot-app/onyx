import json
from datetime import datetime
from datetime import timedelta
from typing import cast

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from danswer.configs.app_configs import TOKEN_BUDGET_GLOBALLY_ENABLED
from danswer.configs.constants import ENABLE_TOKEN_BUDGET
from danswer.configs.constants import TOKEN_BUDGET
from danswer.configs.constants import TOKEN_BUDGET_SETTINGS
from danswer.configs.constants import TOKEN_BUDGET_TIME_PERIOD
from danswer.db.engine import get_session_context_manager
from danswer.db.models import ChatMessage
from danswer.dynamic_configs.factory import get_dynamic_config_store

BUDGET_LIMIT_DEFAULT = -1  # Default to no limit
TIME_PERIOD_HOURS_DEFAULT = 12


def is_under_token_budget(db_session: Session) -> bool:
    try:
        settings_json = cast(
            str, get_dynamic_config_store().load(TOKEN_BUDGET_SETTINGS)
        )
    except Exception:
        return True

    settings = json.loads(settings_json)

    is_enabled = settings.get(ENABLE_TOKEN_BUDGET, False)

    if not is_enabled:
        return True

    budget_limit = settings.get(TOKEN_BUDGET, -1)

    if budget_limit < 0:
        return True

    period_hours = settings.get(TOKEN_BUDGET_TIME_PERIOD, TIME_PERIOD_HOURS_DEFAULT)
    period_start_time = datetime.now() - timedelta(hours=period_hours)

    # Fetch the sum of all tokens used within the period
    token_sum = (
        db_session.query(func.sum(ChatMessage.token_count))
        .filter(ChatMessage.time_sent >= period_start_time)
        .scalar()
        or 0
    )

    print(
        "token_sum:",
        token_sum,
        "budget_limit:",
        budget_limit,
        "period_hours:",
        period_hours,
        "period_start_time:",
        period_start_time,
    )

    return token_sum < (
        budget_limit * 1000
    )  # Budget limit is expressed in thousands of tokens


def check_token_budget() -> None:
    if not TOKEN_BUDGET_GLOBALLY_ENABLED:
        return None

    with get_session_context_manager() as db_session:
        # Perform the token budget check here, possibly using `user` and `db_session` for database access if needed
        if not is_under_token_budget(db_session):
            raise HTTPException(
                status_code=429, detail="Sorry, token budget exceeded. Try again later."
            )
