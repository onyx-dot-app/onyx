"""add_tenant_invite_counter_table

Revision ID: d4e7a92c1b38
Revises: 3b9f09038764
Create Date: 2026-04-20 18:00:00.000000

Adds `public.tenant_invite_counter`, the lifetime invite-quota counter used by
the trial-tenant cap in `bulk_invite_users`. One row per tenant; holds a
monotonically-incremented total of invites ever reserved by that tenant.

Why we need it:
    Trial tenants are capped at NUM_FREE_TRIAL_USER_INVITES per lifetime.
    A counter derived from the mutable KV-backed invited-users list can be
    reset by the remove-invited-user endpoint (each removal pops a KV
    entry, lowering the effective count), allowing the cap to be bypassed
    by looping invite → remove → invite. This table stores a counter that
    is only ever incremented; no endpoint decrements it, so removals do
    not free up quota.

How it works:
    Each call to `bulk_invite_users` for a trial tenant runs a single atomic
    UPSERT:

        INSERT INTO public.tenant_invite_counter (tenant_id, total_invites_sent)
        VALUES (:tid, :n)
        ON CONFLICT (tenant_id) DO UPDATE
          SET total_invites_sent = tenant_invite_counter.total_invites_sent + EXCLUDED.total_invites_sent,
              updated_at = NOW()
        RETURNING total_invites_sent;

    The UPDATE takes a row-level lock on `tenant_id`, so concurrent bulk-
    invite flows for the same tenant are serialized without an advisory
    lock. If the returned total exceeds the cap the caller ROLLBACKs so the
    reservation does not stick. Paid tenants skip this path entirely.

Deploy-time behavior:
    The table ships empty. Trial tenants with pre-existing KV invited-users
    entries are not seeded, so each one's counter starts at 0 and can
    issue one additional full batch (up to NUM_FREE_TRIAL_USER_INVITES)
    before the monotonic guard engages. Scope of the gap is bounded to
    one batch per trial tenant and does not recur; backfill was
    intentionally skipped to keep this migration pure-DDL.

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e7a92c1b38"
down_revision = "3b9f09038764"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_invite_counter",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "total_invites_sent",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("tenant_invite_counter", schema="public")
