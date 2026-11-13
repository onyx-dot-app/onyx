# Jira Service Management Connector

The Jira Service Management (JSM) connector allows Danswer to pull in tickets and knowledge articles from specified JSM projects, making them searchable within the Danswer platform.

## Features

*   **Ticket Ingestion**: Fetches tickets (Service Requests, Incidents, Problems, Changes, etc.) from one or more JSM projects.
*   **Configurable JQL**: Allows specifying a custom JQL query to precisely control which tickets are ingested.
*   **Attachments & Comments**: Optionally includes attachments and comments associated with tickets.
*   **Metadata Extraction**: Extracts key metadata such as summary, description, status, reporter, assignee, creation/update times, and JSM-specific fields like "Request Type" (if available).
*   **Permissions Sync**: Inherits permission syncing capabilities from the base Jira connector, ensuring users only see documents they have access to.

## Configuration

To set up the Jira Service Management connector, you will need the following information:

1.  **Jira URL**: The base URL of your Jira instance (e.g., `https://your-company.atlassian.net`).
2.  **Jira Username**: The email address of a Jira user with appropriate permissions to access the desired JSM projects.
3.  **Jira API Token**: An API token generated for the Jira username.
    *   To generate an API token, go to [https://id.atlassian.com/manage-api-tokens](https://id.atlassian.com/manage-api-tokens) and click "Create API token".
4.  **Project Keys**: A comma-separated list of JSM project keys (e.g., `SERVICE,HELPDESK,ITSM`). Only tickets from these projects will be ingested.
5.  **Include Attachments**: (Optional) Check this box to include file attachments from Jira tickets.
6.  **Include Comments**: (Optional) Check this box to include comments from Jira tickets.
7.  **Include Subtasks**: (Optional) Check this box to include subtasks. By default, only parent tasks are included.
8.  **Custom JQL Query**: (Optional) Provide a custom [Jira Query Language (JQL)](https://support.atlassian.com/jira-service-management-cloud/docs/use-advanced-searching-with-jql/) query to filter tickets. If provided, this query will override the default JSM-specific filter.
    *   **Default JQL Filter**: If no custom JQL is provided, the connector uses a default filter to include common JSM issue types: `issuetype in ('Service Request', 'Incident', 'Problem', 'Change', 'Service Request with Approvals', 'Customer Request', 'Support Request', 'Task', 'Story', 'Bug') OR issuetype in standardIssueTypes()`.

### Permissions Required

The Jira user associated with the API token needs at least "Browse Projects" permission for the specified JSM projects and "View Issues" permission for the tickets within those projects. To fetch attachments and comments, "View Attachments" and "View Comments" permissions are also required.

## How it Works

The connector leverages the existing Jira connector's robust API interaction capabilities. It extends the base Jira functionality by:

*   Applying a default JQL filter specifically tailored for common Jira Service Management issue types.
*   Enhancing document metadata with JSM-specific fields if they are present in the raw Jira issue data (e.g., "Request Type").

## Development Notes

*   The connector is built upon the `danswer.connectors.jira.connector.JiraConnector` class, inheriting most of its core logic for API interaction, pagination, and document conversion.
*   JSM-specific logic primarily resides in the `_get_jql_query` method to apply relevant filters and in `_jira_issue_to_document` to extract additional JSM metadata.
*   Webhooks are not currently supported for the JSM connector, as JSM often relies on different notification mechanisms or the existing Jira webhook system is sufficient for general issue updates.
