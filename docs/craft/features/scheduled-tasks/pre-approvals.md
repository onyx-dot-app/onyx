# Scheduled task action policies

Scheduled tasks now store permissions for individual actions. Whole-app pre-approvals are replaced by the Apps and MCP servers cards.

New tasks start with all apps disabled. Enabling an app reveals Approval settings and copies the user's current choices. Disabling an app blocks its requests and retains its choices. Enabling it again restores those choices. Later personal changes do not affect existing tasks. Task edits affect subsequent requests, including requests from an active run.

Task-disabled apps and workspace-disabled actions remain blocked. When users cannot manage an app's permissions, workspace settings apply. Otherwise task settings apply, with Ask as the fallback for missing actions.

Approve once and Approve for session remain available. Session approval covers specific actions and cannot override Disabled. The proxy waits up to 180 seconds; it does not durably pause execution.

The migration converts known actions only in apps a task previously pre-approved. It creates no settings for other apps. Some actions that previously ran automatically may now require approval. The old grant table and runtime cache are removed.

See the [scheduled-task feature map](../../../../.agents/feature-map/components/craft-scheduled-tasks.md) for the API, storage, enforcement rules, and tests.
