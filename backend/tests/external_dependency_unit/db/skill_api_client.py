"""Test client for skill routes with an optional API-token scope cap."""

from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth_check import check_router_auth
from onyx.server.features.skill.api import user_router


def client_for(
    user: User,
    session: Session,
    scopes: list[Permission] | None = None,
    routers: tuple[APIRouter, ...] = (),
) -> TestClient:
    app = FastAPI()
    app.include_router(user_router)
    for router in routers:
        app.include_router(router)
    register_onyx_exception_handlers(app)

    def actor(request: Request) -> User:
        request.state.token_scopes = scopes
        return user

    app.dependency_overrides[current_user] = actor
    app.dependency_overrides[get_session] = lambda: session
    check_router_auth(app)
    return TestClient(app)
