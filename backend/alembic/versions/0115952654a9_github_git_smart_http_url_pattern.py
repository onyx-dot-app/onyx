"""github git smart-http url pattern

``upstream_url_patterns`` is snapshotted onto the ``external_app`` row at
creation (tenant provisioning / admin create), so existing GitHub apps only
claim ``api.github.com``. Append the github.com git smart-HTTP pattern (added
to the provider spec in the same change) so the proxy injects credentials for
``git clone``/``fetch``/``push`` on already-installed apps too.

Revision ID: 0115952654a9
Revises: 1cb59a95b250
Create Date: 2026-06-11 10:51:38.157515

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0115952654a9"
down_revision = "1cb59a95b250"
branch_labels = None
depends_on = None

# Keep in sync with _GIT_SMART_HTTP_URL_PATTERN in
# onyx/external_apps/providers/github.py (migrations don't import app code).
_GIT_SMART_HTTP_URL_PATTERN = (
    r"https://github\.com/[^/]+/[^/]+/"
    r"(info/refs|git-upload-pack|git-receive-pack)(\?.*)?"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE external_app "
            "SET upstream_url_patterns = "
            "array_append(upstream_url_patterns, :pattern) "
            "WHERE app_type = 'GITHUB' "
            "AND NOT (:pattern = ANY(upstream_url_patterns))"
        ).bindparams(pattern=_GIT_SMART_HTTP_URL_PATTERN)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE external_app "
            "SET upstream_url_patterns = "
            "array_remove(upstream_url_patterns, :pattern) "
            "WHERE app_type = 'GITHUB'"
        ).bindparams(pattern=_GIT_SMART_HTTP_URL_PATTERN)
    )
