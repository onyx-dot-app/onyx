# Index a Jira Service Management project

The existing Jira connector can index Jira Service Management (JSM) project
issues. JSM exposes the Jira platform APIs used by this connector.
See [Atlassian's API overview](https://developer.atlassian.com/cloud/jira/service-desk/rest/intro).

This setup uses the existing **Jira** source. It does not add a separate source
or use the JSM customer-request API.

## Set up the connector

1. Create a Jira account with access to the service-desk project and its issues.
2. Open **Add Connector**, then select **Jira**.
3. Enter the site URL, such as `https://example.atlassian.net`.
4. Select the **Project** scope and enter the project key, such as `HELP`.
5. Add the credential, then run the indexing checks.
6. Select connector access that matches the sensitivity of the indexed tickets.
7. Create the connector and check its indexing status.

For Cloud, use the account email and API token. Enable the scoped-token setting
if the token uses scopes. For Data Center, use a personal access token.
Follow the [Jira connector setup guide](https://docs.onyx.app/admins/connectors/official/jira)
for credential permissions and capability checks.

Use an account that can browse every issue you need. A customer account's view
can be limited to that customer's requests. A successful sync only covers issues
visible to the credential.

The project scope produces a filter such as:

```text
project = "HELP" AND updated >= <start-in-epoch-ms> AND updated <= <end-in-epoch-ms>
```

Custom JQL takes precedence over the project key. Leave custom JQL blank when
you want the project key to define the scope.

## Indexed content and access

Tickets use stable `/browse/HELP-123` document IDs. The connector indexes their
summary, description, returned comments, owners, status, priority and issue type.
Cloud rich text uses Atlassian Document Format; Data Center text uses strings.
Checkpointing, incremental updates and slim listing use the existing Jira paths.

The connector can include public replies and internal agent notes returned by
Jira. It excludes comments from blacklisted author email addresses and skips
comments that fail processing. It does not filter by JSM public/internal
visibility. Check the account's returned content before sharing a connector
with a wider audience.

Jira permission sync does not implement JSM customer-portal or comment-level
access. Do not use it as a substitute for those access rules. Use restricted
connector access when tickets contain agent-only content.

This path does not extract JSM request types, SLAs, approvals, organizations or
attachment contents. Those need separate source-specific work.

## Verification

Run the fixture-backed regression tests from the repository root:

```bash
uv run pytest -v backend/tests/unit/onyx/connectors/jira/test_jira_service_management.py
```

The tests cover Cloud and Data Center responses, service-desk issue types,
checkpoint continuation, project/time filters, rich text, comment handling,
full/slim ID parity, and authentication failures during listing.

These tests mock the Jira gateway. They do not replace a live JSM setup test.
For live validation, use a test project with multiple tickets, public replies
and internal notes. Create the connector in the UI, inspect indexed content,
update a ticket, then verify the next sync. Confirm the selected connector
access before adding other users.
