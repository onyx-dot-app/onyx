# Jira Service Management Connector

This connector pulls in all tickets from a specified Jira Service Management project.

## Configuration

The connector requires the following configuration:

### Required Fields
- `base_url`: Base URL of your Jira instance (e.g., `https://your-domain.atlassian.net`)
- `project_key`: Project key to fetch tickets from (e.g., `ITSM`)

### Authentication (choose one)
- `email` + `api_token`: Email address and API token for Jira account
- `personal_access_token`: Personal Access Token for Jira authentication

### Optional Fields
- `batch_size`: Number of issues to fetch per API call (default: 100, min: 1, max: 100)
- `include_comments`: Whether to include comments in the document content (default: true)
- `include_attachments`: Whether to include attachment content (default: false, requires additional API calls)
- `jql_query`: Custom JQL query to filter issues (overrides default project filter)

## Authentication Setup

### Option 1: API Token
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a name (e.g., "Danswer Connector")
4. Copy the token immediately (you won't be able to see it again)
5. Use your email and this token in the connector configuration

### Option 2: Personal Access Token
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create and manage API tokens" then "Create a personal access token"
3. Follow the prompts to create a token with appropriate scopes
4. Use this token in the connector configuration

## Scopes Required

The connector requires the following scopes:
- `read:jira-work` - Read Jira issues and projects
- `read:jira-user`