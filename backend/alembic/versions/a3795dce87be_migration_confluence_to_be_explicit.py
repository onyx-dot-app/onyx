"""migration confluence to be explicit

Revision ID: a3795dce87be
Revises: 1f60f60c3401
Create Date: 2024-09-01 13:52:12.006740

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import table, column

revision = "a3795dce87be"
down_revision = "1f60f60c3401"
branch_labels: None = None
depends_on: None = None


def extract_confluence_keys_from_url(wiki_url: str) -> tuple[str, str, str, bool]:
    from urllib.parse import urlparse

    def _extract_confluence_keys_from_cloud_url(wiki_url: str) -> tuple[str, str, str]:
        parsed_url = urlparse(wiki_url)
        wiki_base = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.split('/spaces')[0]}"
        path_parts = parsed_url.path.split("/")
        space = path_parts[3]
        page_id = path_parts[5] if len(path_parts) > 5 else ""
        return wiki_base, space, page_id

    def _extract_confluence_keys_from_datacenter_url(
        wiki_url: str,
    ) -> tuple[str, str, str]:
        DISPLAY = "/display/"
        PAGE = "/pages/"
        parsed_url = urlparse(wiki_url)
        wiki_base = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.split(DISPLAY)[0]}"
        space = DISPLAY.join(parsed_url.path.split(DISPLAY)[1:]).split("/")[0]
        page_id = ""
        if (content := parsed_url.path.split(PAGE)) and len(content) > 1:
            page_id = content[1]
        return wiki_base, space, page_id

    is_confluence_cloud = (
        ".atlassian.net/wiki/spaces/" in wiki_url
        or ".jira.com/wiki/spaces/" in wiki_url
    )

    if is_confluence_cloud:
        wiki_base, space, page_id = _extract_confluence_keys_from_cloud_url(wiki_url)
    else:
        wiki_base, space, page_id = _extract_confluence_keys_from_datacenter_url(
            wiki_url
        )

    return wiki_base, space, page_id, is_confluence_cloud


def reconstruct_confluence_url(
    wiki_base: str, space: str, page_id: str, is_cloud: bool
) -> str:
    if is_cloud:
        url = f"{wiki_base}/spaces/{space}"
        if page_id:
            url += f"/pages/{page_id}"
    else:
        url = f"{wiki_base}/display/{space}"
        if page_id:
            url += f"/pages/{page_id}"
    return url


def upgrade() -> None:
    connector = table(
        "connector",
        column("id", sa.Integer),
        column("source", sa.String()),
        column("input_type", sa.String()),
        column("connector_specific_config", postgresql.JSONB),
    )

    # Fetch all Confluence connectors
    connection = op.get_bind()
    confluence_connectors = connection.execute(
        sa.select(connector).where(
            sa.and_(
                connector.c.source == "CONFLUENCE", connector.c.input_type == "POLL"
            )
        )
    ).fetchall()

    for row in confluence_connectors:
        config = row.connector_specific_config
        wiki_page_url = config["wiki_page_url"]
        wiki_base, space, page_id, is_cloud = extract_confluence_keys_from_url(
            wiki_page_url
        )

        new_config = {
            "wiki_base": wiki_base,
            "space": space,
            "page_id": page_id,
            "is_cloud": is_cloud,
        }

        for key, value in config.items():
            if key not in ["wiki_page_url"]:
                new_config[key] = value

        op.execute(
            connector.update()
            .where(connector.c.id == row.id)
            .values(connector_specific_config=new_config)
        )


def downgrade() -> None:
    connector = table(
        "connector",
        column("id", sa.Integer),
        column("source", sa.String()),
        column("input_type", sa.String()),
        column("connector_specific_config", postgresql.JSONB),
    )

    confluence_connectors = (
        op.get_bind()
        .execute(
            sa.select(connector).where(
                connector.c.source == "CONFLUENCE", connector.c.input_type == "POLL"
            )
        )
        .fetchall()
    )

    for row in confluence_connectors:
        config = row.connector_specific_config
        if all(key in config for key in ["wiki_base", "space", "is_cloud"]):
            wiki_page_url = reconstruct_confluence_url(
                config["wiki_base"],
                config["space"],
                config.get("page_id", ""),
                config["is_cloud"],
            )

            new_config = {"wiki_page_url": wiki_page_url}
            new_config.update(
                {
                    k: v
                    for k, v in config.items()
                    if k not in ["wiki_base", "space", "page_id", "is_cloud"]
                }
            )

            op.execute(
                connector.update()
                .where(connector.c.id == row.id)
                .values(connector_specific_config=new_config)
            )
