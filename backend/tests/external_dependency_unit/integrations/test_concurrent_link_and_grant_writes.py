"""Two requests that write the same user grant, or the same integration link of an
agent, at the same time. The second one must wait for the first, not fail on
the unique key. A write that waited for a delete of the integration gets
NOT_FOUND."""

from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.integration import (
    delete_integration__no_commit,
    list_integration_actions,
)
from onyx.db.integration_policy import list_persona_integration_links
from onyx.db.models import Integration, Persona, User
from onyx.db.persona import upsert_persona
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import ActionSettings, LinkValue, PersonaIntegrationLink
from onyx.integrations.service import member_actions, set_action_grants__no_commit
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_openapi_integration,
)

_SCHEMA: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "races", "version": "1", "description": "races"},
    "servers": [{"url": "https://api.example.test"}],
    "paths": {
        "/send": {
            "post": {
                "operationId": "send",
                "summary": "send",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}
_LOCK_WAIT_S = 10


@pytest.fixture
def integration(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Integration, None, None]:
    created, _ = make_openapi_integration(db_session, openapi_schema=_SCHEMA)
    integration_id = created.id
    try:
        yield created
    finally:
        delete_integrations(db_session, [integration_id])


def _run_second_while_first_is_open(
    db_session: Session,
    first: Callable[[Session], None],
    second: Callable[[Session], None],
) -> None:
    """Run ``first`` without a commit, start ``second`` on a new session, and
    commit ``first`` when ``second`` waits on a lock."""
    bind = db_session.get_bind()

    def run_second() -> None:
        with Session(bind=bind) as session:
            second(session)
            session.commit()

    with Session(bind=bind) as first_session, Session(bind=bind) as observer:
        first(first_session)
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(run_second)
            deadline = monotonic() + _LOCK_WAIT_S
            while not result.done() and monotonic() < deadline:
                waiting = observer.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE NOT granted")
                )
                observer.rollback()
                if waiting:
                    break
            first_session.commit()
            result.result(timeout=_LOCK_WAIT_S)


def test_concurrent_saves_of_one_user_grant_both_succeed(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    user_id = make_test_user("grant_race").id
    integration_id = integration.id
    key = list_integration_actions(integration_id, db_session)[0].key

    def save(session: Session) -> None:
        set_action_grants__no_commit(
            session.get_one(User, user_id),
            session.get_one(Integration, integration_id),
            {key: "allow"},
            session,
        )

    _run_second_while_first_is_open(db_session, save, save)

    db_session.expire_all()
    actions = member_actions(db_session.get_one(User, user_id), integration, db_session)
    assert [action.user_policy for action in actions] == ["allow"]


def test_concurrent_saves_of_one_agent_integration_link_both_succeed(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("link_race")
    persona_id = create_test_persona(db_session, owner).id
    give_access(db_session, [integration])
    link = PersonaIntegrationLink(
        integration_id=integration.id,
        action_settings=ActionSettings(default=LinkValue.ASK),
    )

    def save(session: Session) -> None:
        persona = session.get_one(Persona, persona_id)
        # The same values as the stored agent, so only the link is written.
        upsert_persona(
            user=None,
            name=persona.name,
            description=persona.description,
            starter_messages=None,
            system_prompt=None,
            task_prompt=None,
            datetime_aware=None,
            is_public=None,
            db_session=session,
            integration_links=[link],
            persona_id=persona_id,
            commit=False,
        )

    _run_second_while_first_is_open(db_session, save, save)

    db_session.expire_all()
    links = list_persona_integration_links(db_session, persona_id)
    assert [(row.integration_id, row.action_settings) for row in links] == [
        (integration.id, {"default": "ask"})
    ]


def test_grant_save_that_waited_for_integration_delete_is_not_found(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    user_id = make_test_user("delete_race").id
    integration_id = integration.id
    key = list_integration_actions(integration_id, db_session)[0].key

    def remove(session: Session) -> None:
        delete_integration__no_commit(
            session.get_one(Integration, integration_id), session
        )

    def save(session: Session) -> None:
        set_action_grants__no_commit(
            session.get_one(User, user_id),
            session.get_one(Integration, integration_id),
            {key: "allow"},
            session,
        )

    with pytest.raises(OnyxError) as raised:
        _run_second_while_first_is_open(db_session, remove, save)
    assert raised.value.error_code is OnyxErrorCode.NOT_FOUND
