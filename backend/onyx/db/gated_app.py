"""The ``gated_app`` identity row: get-or-create, lookup, and the per-action
policy read/write shared by every gated target (external app or MCP server).

All mapping between a gated target ``(kind, target_id)`` and its ``gated_app``
row lives here; consumers reference ``gated_app_id`` only, never the per-catalog
columns.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import EndpointPolicy, GatedAppKind
from onyx.db.models import GatedActionPolicy, GatedApp


class StoredActionPolicies(BaseModel):
    """Stored per-action policy overrides as ``{target_id: {action_id: policy}}``.
    Sparse — only actions an admin has explicitly set; targets with no stored
    overrides are absent."""

    by_target_id: dict[int, dict[str, EndpointPolicy]]

    def for_target(self, target_id: int) -> dict[str, EndpointPolicy]:
        return self.by_target_id.get(target_id, {})


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
    db_session: Session, kind: GatedAppKind, target_ids: list[int]
) -> StoredActionPolicies:
    """The targets' stored per-action policy overrides.

    Single query regardless of target count: joins ``gated_action_policy`` to
    ``gated_app`` so resolving the identity rows and reading their policies is
    one round trip (this runs on the request matching path)."""
    if not target_ids:
        return StoredActionPolicies(by_target_id={})
    target_column = _target_column(kind)
    rows = db_session.execute(
        select(target_column, GatedActionPolicy.action_id, GatedActionPolicy.policy)
        .join(GatedApp, GatedApp.id == GatedActionPolicy.gated_app_id)
        .where(target_column.in_(target_ids))
    ).all()
    by_target_id: dict[int, dict[str, EndpointPolicy]] = {}
    for target_id, action_id, policy in rows:
        by_target_id.setdefault(target_id, {})[action_id] = policy
    return StoredActionPolicies(by_target_id=by_target_id)


def get_action_policies_for_target(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> dict[str, EndpointPolicy]:
    """Single-target convenience over ``get_action_policies``: the target's
    stored ``{action_id: policy}`` overrides, ``{}`` when none are set."""
    return get_action_policies(db_session, kind, [target_id]).for_target(target_id)


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
