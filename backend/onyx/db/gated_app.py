"""The ``gated_app`` identity row: get-or-create, lookup, and the per-action
policy read/write shared by every gated target (external app or MCP server).

All mapping between a gated target ``(kind, target_id)`` and its ``gated_app``
row lives here; consumers reference ``gated_app_id`` only, never the per-catalog
columns.
"""

from __future__ import annotations

from sqlalchemy import delete, insert, select
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
    target_column = _target_column(kind).key
    db_session.execute(
        pg_insert(GatedApp)
        .values({target_column: target_id})
        .on_conflict_do_nothing(index_elements=[target_column])
    )
    db_session.flush()
    created = get_gated_app_id(db_session, kind, target_id)
    if created is None:
        # Unreachable barring a concurrent delete: we just inserted, or a
        # concurrent writer did.
        raise RuntimeError(
            f"gated_app row missing after insert for kind {kind} target_id {target_id}"
        )
    return created


def get_action_policies(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> dict[str, EndpointPolicy]:
    """The target's stored per-action policy overrides as
    ``{action_id: policy}``; ``{}`` when none are set. Sparse — only actions an
    admin has explicitly set. One query: joins ``gated_action_policy`` to
    ``gated_app`` (this runs on the request matching path)."""
    rows = db_session.execute(
        select(GatedActionPolicy.action_id, GatedActionPolicy.policy)
        .join(GatedApp, GatedApp.id == GatedActionPolicy.gated_app_id)
        .where(_target_column(kind) == target_id)
    ).all()
    return {action_id: policy for action_id, policy in rows}


def replace_action_policies__no_commit(
    db_session: Session,
    gated_app_id: int,
    policies: dict[str, EndpointPolicy],
) -> None:
    """Replace ``gated_app_id``'s per-action policy rows with exactly ``policies``.

    DELETE then one bulk INSERT, emitted in order so a re-set action can't
    collide with its old row on ``uq_gated_action_policy``. No commit — runs
    inside the caller's transaction.
    """
    db_session.execute(
        delete(GatedActionPolicy).where(GatedActionPolicy.gated_app_id == gated_app_id)
    )
    if policies:
        db_session.execute(
            insert(GatedActionPolicy),
            [
                {"gated_app_id": gated_app_id, "action_id": action_id, "policy": policy}
                for action_id, policy in policies.items()
            ],
        )


def set_action_policies__no_commit(
    db_session: Session,
    kind: GatedAppKind,
    target_id: int,
    policies: dict[str, EndpointPolicy],
) -> None:
    """Replace ``(kind, target_id)``'s per-action policy overrides with exactly
    ``policies``, creating the ``gated_app`` row if absent. No commit — runs
    inside the caller's transaction."""
    gated_app_id = get_or_create_gated_app_id(db_session, kind, target_id)
    replace_action_policies__no_commit(db_session, gated_app_id, policies)
