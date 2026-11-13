# Default JQL filter for Jira Service Management tickets.
# This aims to include common JSM issue types like Service Request, Incident, Problem, Change,
# but also allows for custom types. It's a broad filter.
# Users can override this with `custom_jql_query`.
JSM_DEFAULT_JQL_FILTER = (
    "issuetype in ('Service Request', 'Incident', 'Problem', 'Change', 'Service Request with Approvals', "
    "'Customer Request', 'Support Request', 'Task', 'Story', 'Bug') OR issuetype in standardIssueTypes()"
)

# Connector name for display and internal identification
JSM_CONNECTOR_NAME = "JiraServiceManagement"
