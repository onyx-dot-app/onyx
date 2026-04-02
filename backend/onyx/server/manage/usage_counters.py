from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.usage import acknowledge_user_counters
from onyx.db.usage import get_counter_definitions
from onyx.db.usage import get_user_counters

router = APIRouter(prefix="/usage")


class CounterResponse(BaseModel):
    key: str
    title: str
    description: str
    hint: str
    icon: str
    target: int
    current: int
    completed_at: str | None
    acknowledged: bool


class AckRequest(BaseModel):
    keys: list[str]


@router.get("/user-counters")
def get_user_counters_api(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[CounterResponse]:
    definitions = get_counter_definitions()
    rows = get_user_counters(db_session, user.id)
    row_map = {r.counter_key: r for r in rows}

    result = []
    for defn in definitions:
        row = row_map.get(defn["key"])
        result.append(
            CounterResponse(
                key=defn["key"],
                title=defn["title"],
                description=defn["description"],
                hint=defn["hint"],
                icon=defn["icon"],
                target=defn["target"],
                current=row.current_value if row else 0,
                completed_at=(
                    row.completed_at.isoformat() if row and row.completed_at else None
                ),
                acknowledged=row.acknowledged if row else False,
            )
        )
    return result


@router.patch("/user-counters/ack")
def acknowledge_counters_api(
    req: AckRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    acknowledge_user_counters(db_session, user.id, req.keys)
    db_session.commit()
