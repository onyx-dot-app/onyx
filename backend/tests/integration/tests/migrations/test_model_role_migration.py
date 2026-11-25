"""Migration 609429379ca0: the `is_default` flags on `llm_model_flow` and
`image_generation_config` become rows of `model_role`, and the job flow rows
(CHAT_NAMING, SEARCH_SELECTION, CRAFT, CONTEXTUAL_RAG) are deleted."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "ce6d912380d7"


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def _insert_model(
    conn: Connection, provider_id: int, name: str, flows: list[str]
) -> int:
    model_id = conn.execute(
        text(
            "INSERT INTO model_configuration (llm_provider_id, name, is_visible) "
            "VALUES (:provider_id, :name, true) RETURNING id"
        ),
        {"provider_id": provider_id, "name": name},
    ).scalar_one()
    for flow in flows:
        conn.execute(
            text(
                "INSERT INTO llm_model_flow "
                "(llm_model_flow_type, model_configuration_id, is_default) "
                "VALUES (:flow, :model_id, false)"
            ),
            {"flow": flow, "model_id": model_id},
        )
    return model_id


def _make_default(conn: Connection, model_id: int, flow: str) -> None:
    conn.execute(
        text(
            "UPDATE llm_model_flow SET is_default = false WHERE llm_model_flow_type = :flow"
        ),
        {"flow": flow},
    )
    conn.execute(
        text(
            "UPDATE llm_model_flow SET is_default = true "
            "WHERE llm_model_flow_type = :flow AND model_configuration_id = :id"
        ),
        {"flow": flow, "id": model_id},
    )


def test_defaults_become_roles(engine: Engine) -> None:
    suffix = uuid4().hex[:8]
    with engine.begin() as conn:
        conn.execute(text("UPDATE image_generation_config SET is_default = false"))
        provider_id = conn.execute(
            text(
                "INSERT INTO llm_provider (name, provider) "
                "VALUES (:name, 'openai') RETURNING id"
            ),
            {"name": f"roles-{suffix}"},
        ).scalar_one()
        chat = _insert_model(
            conn,
            provider_id,
            f"chat-{suffix}",
            ["CHAT", "VISION", "CHAT_NAMING", "SEARCH_SELECTION", "CRAFT"],
        )
        decision = _insert_model(conn, provider_id, f"decision-{suffix}", ["DECISION"])
        image = _insert_model(
            conn, provider_id, f"image-{suffix}", ["IMAGE_GENERATION", "CONTEXTUAL_RAG"]
        )
        for flow in ("CHAT", "VISION", "CHAT_NAMING", "SEARCH_SELECTION", "CRAFT"):
            _make_default(conn, chat, flow)
        _make_default(conn, decision, "DECISION")
        conn.execute(
            text(
                "INSERT INTO image_generation_config "
                "(image_provider_id, model_configuration_id, is_default) "
                "VALUES (:id, :model_id, true)"
            ),
            {"id": f"image-{suffix}", "model_id": image},
        )

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")

    with engine.connect() as conn:
        roles: dict[str, int | None] = dict(
            conn.execute(text("SELECT role, model_configuration_id FROM model_role"))
            .tuples()
            .all()
        )
        flows = {
            (model_id, flow)
            for model_id, flow in conn.execute(
                text(
                    "SELECT model_configuration_id, llm_model_flow_type "
                    "FROM llm_model_flow WHERE model_configuration_id = ANY(:ids)"
                ),
                {"ids": [chat, decision, image]},
            ).all()
        }

    assert roles == {
        "CHAT": chat,
        "IMAGE_PROCESSING": chat,
        "CHAT_NAMING": chat,
        "SEARCH_SELECTION": chat,
        "CRAFT": chat,
        "DECISION": decision,
        "IMAGE_GENERATION": image,
    }
    assert flows == {
        (chat, "CHAT"),
        (chat, "VISION"),
        (decision, "DECISION"),
        (image, "IMAGE_GENERATION"),
    }

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM model_role WHERE model_configuration_id = ANY(:ids)"),
            {"ids": [chat, decision, image]},
        )
        conn.execute(
            text("DELETE FROM image_generation_config WHERE image_provider_id = :id"),
            {"id": f"image-{suffix}"},
        )
        conn.execute(
            text("DELETE FROM llm_provider WHERE id = :id"), {"id": provider_id}
        )
