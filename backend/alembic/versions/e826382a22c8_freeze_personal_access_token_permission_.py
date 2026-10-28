"""Freeze personal access token permission caps.

Revision ID: e826382a22c8
Revises: ca7cc9a98a6b
Create Date: 2026-10-28 09:51:23.845426

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e826382a22c8"
down_revision = "ca7cc9a98a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_access_token",
        sa.Column("permission_cap", postgresql.JSONB(), nullable=True),
    )
    # Freeze this graph. Importing application permissions could widen old tokens
    # when a future release changes their implications.
    # CE grants add:agents outside stored permissions. Include it for legacy
    # compatibility; the live owner permission check still limits EE requests.
    op.execute(
        """
        WITH RECURSIVE known_permissions(permission) AS (
            VALUES
                ('basic'),
                ('read:connectors'),
                ('read:document_sets'),
                ('read:agents'),
                ('read:users'),
                ('read:user_groups'),
                ('read:search'),
                ('read:chat'),
                ('write:chat'),
                ('read:admin'),
                ('generate:image'),
                ('use:llm_gateway'),
                ('add:agents'),
                ('manage:agents'),
                ('manage:document_sets'),
                ('manage:connectors'),
                ('manage:llms'),
                ('read:agent_analytics'),
                ('manage:actions'),
                ('manage:skills'),
                ('read:query_history'),
                ('manage:user_groups'),
                ('create:user_api_keys'),
                ('manage:service_account_api_keys'),
                ('manage:bots'),
                ('craft_sandbox'),
                ('admin')
        ), implications(granted, implied) AS (
            VALUES
                ('manage:agents', 'add:agents'),
                ('manage:agents', 'read:agents'),
                ('manage:agents', 'read:document_sets'),
                ('manage:agents', 'read:agent_analytics'),
                ('manage:document_sets', 'read:document_sets'),
                ('manage:document_sets', 'read:connectors'),
                ('manage:document_sets', 'read:user_groups'),
                ('manage:connectors', 'read:connectors'),
                ('manage:connectors', 'read:user_groups'),
                ('manage:user_groups', 'read:connectors'),
                ('manage:user_groups', 'read:document_sets'),
                ('manage:user_groups', 'read:agents'),
                ('manage:user_groups', 'read:users'),
                ('manage:user_groups', 'read:user_groups'),
                ('manage:llms', 'read:user_groups'),
                ('manage:llms', 'read:agents'),
                ('manage:llms', 'read:users'),
                ('manage:service_account_api_keys', 'read:user_groups'),
                ('manage:actions', 'read:user_groups'),
                ('basic', 'read:search'),
                ('basic', 'read:chat'),
                ('basic', 'write:chat'),
                ('basic', 'generate:image'),
                ('basic', 'use:llm_gateway'),
                ('write:chat', 'read:chat'),
                ('craft_sandbox', 'read:search'),
                ('craft_sandbox', 'generate:image'),
                ('craft_sandbox', 'use:llm_gateway')
            UNION
            SELECT 'admin', permission FROM known_permissions
        ), owners AS (
            SELECT DISTINCT user_id FROM personal_access_token
        ), owner_permissions(user_id, permission, authority) AS (
            SELECT owner.id, known.permission, 'global'
            FROM "user" AS owner
            JOIN owners ON owners.user_id = owner.id
            CROSS JOIN LATERAL jsonb_array_elements_text(
                NULLIF(owner.effective_permissions, 'null'::jsonb)
            ) AS direct(permission)
            JOIN known_permissions AS known ON known.permission = direct.permission
            UNION
            SELECT owner.id, 'add:agents', 'global'
            FROM "user" AS owner
            JOIN owners ON owners.user_id = owner.id
            WHERE NOT owner.is_group_manager
            UNION
            SELECT owner.id, scoped.permission, 'scoped'
            FROM "user" AS owner
            JOIN owners ON owners.user_id = owner.id
            CROSS JOIN (
                VALUES
                    ('manage:connectors'),
                    ('manage:document_sets'),
                    ('manage:agents'),
                    ('add:agents'),
                    ('manage:user_groups'),
                    ('manage:actions'),
                    ('manage:skills')
            ) AS scoped(permission)
            WHERE owner.is_group_manager
            UNION
            SELECT owner.user_id, implications.implied, owner.authority
            FROM owner_permissions AS owner
            JOIN implications ON implications.granted = owner.permission
        ), selected_permissions(token_id, permission) AS (
            SELECT token.id, known.permission
            FROM personal_access_token AS token
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(NULLIF(token.scopes, 'null'::jsonb), '[]'::jsonb)
            ) AS direct(permission)
            JOIN known_permissions AS known ON known.permission = direct.permission
            UNION
            SELECT selected.token_id, implications.implied
            FROM selected_permissions AS selected
            JOIN implications ON implications.granted = selected.permission
        ), capped_permissions(token_id, permission, authority) AS (
            SELECT token.id, owner.permission,
                   CASE WHEN token.pat_type = 'CRAFT' THEN 'global' ELSE owner.authority END
            FROM personal_access_token AS token
            JOIN owner_permissions AS owner ON owner.user_id = token.user_id
            WHERE (
                NULLIF(token.scopes, 'null'::jsonb) IS NULL
                OR EXISTS (
                    SELECT 1 FROM selected_permissions AS selected
                    WHERE selected.token_id = token.id
                      AND selected.permission = owner.permission
                )
            )
            AND (token.pat_type = 'CRAFT' OR owner.permission <> 'craft_sandbox')
            AND (
                token.pat_type = 'CRAFT'
                OR owner.permission <> 'use:llm_gateway'
                OR token.scopes ? 'use:llm_gateway'
            )
            UNION
            SELECT token.id, 'craft_sandbox', 'global'
            FROM personal_access_token AS token
            JOIN selected_permissions AS selected ON selected.token_id = token.id
            WHERE token.pat_type = 'CRAFT'
              AND selected.permission = 'craft_sandbox'
        ), strongest_permissions AS (
            SELECT token_id, permission,
                   CASE WHEN bool_or(authority = 'global') THEN 'global' ELSE 'scoped' END AS authority
            FROM capped_permissions
            GROUP BY token_id, permission
        ), caps AS (
            SELECT token_id, jsonb_object_agg(permission, authority) AS permissions
            FROM strongest_permissions
            GROUP BY token_id
        )
        UPDATE personal_access_token AS token
        SET permission_cap = COALESCE(
            (SELECT permissions FROM caps WHERE caps.token_id = token.id),
            '{}'::jsonb
        )
        """
    )
    op.alter_column("personal_access_token", "permission_cap", nullable=False)


def downgrade() -> None:
    op.drop_column("personal_access_token", "permission_cap")
