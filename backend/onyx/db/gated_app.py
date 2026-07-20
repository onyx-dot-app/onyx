"""The ``gated_app`` identity row: get-or-create, lookup, and the per-action
policy read/write shared by every gated target (external app or MCP server).

All mapping between a gated target ``(kind, target_id)`` and its ``gated_app``
row lives here; consumers reference ``gated_app_id`` only, never the per-catalog
columns.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import EndpointPolicy, GatedAppKind
from onyx.db.models import GatedActionPolicy, GatedApp


def _target_column(kind: GatedAppKind) -> InstrumentedAttribute[int | None]:
    return (
        GatedApp.external_app_id
        if kind is GatedAppKind.EXTERNAL_APP
        else GatedApp.mcp_server_id
    )


def get_gated_app_id(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> int | None:
    """The ``gated_app`` row id for ``(kind, target_id)``, or ``None`` when the
    target has no identity row yet (nothing has policied/approved it)."""
    return db_session.scalar(
        select(GatedApp.id).where(_target_column(kind) == target_id)
    )


def get_or_create_gated_app_id(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> int:
    """The ``gated_app`` row id for ``(kind, target_id)``, creating it if absent.

    Race-safe: a concurrent insert is absorbed by ON CONFLICT DO NOTHING on the
    target's unique index, then re-selected. Flushes but does not commit.
    """
    existing = get_gated_app_id(db_session, kind, target_id)
    if existing is not None:
        return existing
    values: dict[str, object] = {"kind": kind}
    if kind is GatedAppKind.EXTERNAL_APP:
        values["external_app_id"] = target_id
        conflict_column = "external_app_id"
    else:
        values["mcp_server_id"] = target_id
        conflict_column = "mcp_server_id"
    db_session.execute(
        pg_insert(GatedApp)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[conflict_column])
    )
    db_session.flush()
    created = get_gated_app_id(db_session, kind, target_id)
    assert created is not None  # just inserted, or a concurrent writer did
    return created


def get_action_policies(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> dict[str, EndpointPolicy]:
    """The target's stored per-action policy overrides as ``{action_id: policy}``.
    Sparse — only actions an admin has explicitly set."""
    gated_app_id = get_gated_app_id(db_session, kind, target_id)
    if gated_app_id is None:
        return {}
    rows = db_session.scalars(
        select(GatedActionPolicy).where(GatedActionPolicy.gated_app_id == gated_app_id)
    ).all()
    return {row.action_id: row.policy for row in rows}


def replace_action_policies__no_commit(
    db_session: Session,
    gated_app_id: int,
    policies: dict[str, EndpointPolicy],
) -> None:
    """Replace ``gated_app_id``'s per-action policy rows with exactly ``policies``.

    DELETEs and flushes before inserting so a re-set action can't collide with
    its not-yet-deleted row on ``uq_gated_action_policy``. No commit — runs
    inside the caller's transaction.
    """
    db_session.execute(
        delete(GatedActionPolicy).where(GatedActionPolicy.gated_app_id == gated_app_id)
    )
    db_session.flush()
    for action_id, policy in policies.items():
        db_session.add(
            GatedActionPolicy(
                gated_app_id=gated_app_id, action_id=action_id, policy=policy
            )
        )
    db_session.flush()
