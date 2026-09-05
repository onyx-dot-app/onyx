import pytest
from sqlalchemy.orm import Session

from onyx.auth.api_key import hash_api_key
from onyx.db.api_key import fetch_api_key_auth_result, insert_api_key, remove_api_key
from onyx.db.engine.async_sql_engine import (
    get_async_session_context_manager,
    reset_sqlalchemy_async_engine,
)
from onyx.db.enums import AccountType
from onyx.server.api_key.models import APIKeyArgs


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_fetch_api_key_auth_result_loads_user(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session, APIKeyArgs(name="auth-result"), user_id=None
    )
    assert descriptor.api_key is not None

    try:
        async with get_async_session_context_manager() as async_session:
            result = await fetch_api_key_auth_result(
                hash_api_key(descriptor.api_key), async_session
            )

        assert result is not None
        # Accessed outside the async session: only possible if eagerly loaded.
        assert result.user.id == descriptor.user_id
        assert result.user.account_type == AccountType.SERVICE_ACCOUNT
        assert result.api_key_id == descriptor.api_key_id
        assert result.api_key_name == "auth-result"
        assert result.api_key_display == descriptor.api_key_display

        async with get_async_session_context_manager() as async_session:
            assert (
                await fetch_api_key_auth_result("not-a-real-hash", async_session)
                is None
            )
    finally:
        remove_api_key(db_session, descriptor.api_key_id)
        # Async pools are bound to this test's event loop; leaving them open
        # makes a later async test fail depending on selection order.
        await reset_sqlalchemy_async_engine()
