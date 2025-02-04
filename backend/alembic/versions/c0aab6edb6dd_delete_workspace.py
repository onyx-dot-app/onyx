"""delete workspace

Revision ID: c0aab6edb6dd
Revises: 35e518e0ddf4
Create Date: 2024-12-17 14:37:07.660631

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c0aab6edb6dd"
down_revision = "35e518e0ddf4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
    UPDATE connector
    SET connector_specific_config = connector_specific_config - 'workspace'
    WHERE source = 'SLACK'
    """
    )


def downgrade() -> None:
    import json
    from sqlalchemy import text
    from slack_sdk import WebClient

    conn = op.get_bind()

    # Fetch all Slack credentials
    creds_result = conn.execute(
        text("SELECT id, credential_json FROM credential WHERE source = 'SLACK'")
    )
    all_slack_creds = creds_result.fetchall()
    if not all_slack_creds:
        return

    for cred_row in all_slack_creds:
        credential_id, credential_json = cred_row

        credential_json = (
            credential_json.tobytes().decode("utf-8")
            if isinstance(credential_json, memoryview)
            else credential_json.decode("utf-8")
        )
        credential_data = json.loads(credential_json)
        slack_bot_token = credential_data.get("slack_bot_token")
        if not slack_bot_token:
            print(
                f"No slack_bot_token found for credential {credential_id}. "
                "Your Slack connector will not function until you upgrade and provide a valid token."
            )
            continue

        client = WebClient(token=slack_bot_token)
        try:
            auth_response = client.auth_test()
            workspace = auth_response["url"].split("//")[1].split(".")[0]

            # Update only the connectors linked to this credential
            # (and which are Slack connectors).
            op.execute(
                f"""
                UPDATE connector AS c
                SET connector_specific_config = jsonb_set(
                    connector_specific_config,
                    '{{workspace}}',
                    to_jsonb('{workspace}'::text)
                )
                FROM connector_credential_pair AS ccp
                WHERE ccp.connector_id = c.id
                  AND c.source = 'SLACK'
                  AND ccp.credential_id = {credential_id}
            """
            )
        except Exception:
            print(
                f"We were unable to get the workspace url for your Slack Connector with id {credential_id}."
            )
            print("This connector will no longer work until you upgrade.")
            continue
