from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.mcp import (
    create_connection_config,
    delete_connection_config,
    mark_connection_config_reauth_required,
    update_connection_config,
)
from onyx.server.features.mcp.credentials import extract_connection_data
from onyx.server.features.mcp.models import MCPConnectionData


@pytest.mark.parametrize("replaced", [False, True])
def test_rejected_credentials_do_not_invalidate_replacement(
    db_session: Session, replaced: bool
) -> None:
    original: MCPConnectionData = {
        "headers": {"Authorization": "Bearer rejected-test-key"}
    }
    config = create_connection_config(original, db_session)
    db_session.commit()
    config_id = config.id
    try:
        if replaced:
            update_connection_config(
                config_id,
                db_session,
                {"headers": {"Authorization": "Bearer replacement-test-key"}},
            )
        marked = mark_connection_config_reauth_required(
            config_id, deepcopy(original), db_session
        )
        db_session.refresh(config)
        data = extract_connection_data(config)
        assert marked is not replaced
        if replaced:
            assert data["headers"]["Authorization"] == "Bearer replacement-test-key"
            assert not data.get("reauth_required", False)
        else:
            assert data["headers"] == original["headers"]
            assert data["reauth_required"] is True
    finally:
        delete_connection_config(config_id, db_session)
        db_session.commit()


@pytest.mark.parametrize("deleted", [False, True])
def test_rejection_uses_current_row_after_concurrent_change(
    db_session: Session, deleted: bool
) -> None:
    original: MCPConnectionData = {"headers": {"Authorization": "Bearer old"}}
    replacement: MCPConnectionData = {"headers": {"Authorization": "Bearer new"}}
    config = create_connection_config(original, db_session)
    db_session.commit()
    config_id = config.id
    # Keep an old snapshot in this session's identity map during another writer.
    db_session.refresh(config)
    try:
        with get_session_with_current_tenant() as writer:
            if deleted:
                delete_connection_config(config_id, writer)
                writer.commit()
            else:
                update_connection_config(config_id, writer, replacement)
        assert extract_connection_data(config) == original
        assert not mark_connection_config_reauth_required(
            config_id, original, db_session
        )
        if not deleted:
            db_session.refresh(config)
            assert extract_connection_data(config) == replacement
    finally:
        if not deleted:
            delete_connection_config(config_id, db_session)
            db_session.commit()
