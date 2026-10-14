# MCP modal story inventory

These stories render the real modals. Each story uses an isolated SWR cache and local API responses.
API writes are simulated. OAuth never redirects to a provider. Unhandled API paths return a local error.

These integration previews include the production data hooks and permission checks, with deterministic network fixtures.

Run `bun run storybook` from `web/`. The links below use its default port.
Use **Reopen preview** to reset form state. Reload the story to reset network fixtures.

## Three-page setup

The creation dialog has server details and authentication steps. Configure authentication saves details before opening authentication. Existing servers use three inline page tabs, including tools.
Server configuration returns to details and keeps both drafts for the same server URL. A changed URL clears authentication for the previous destination.
Existing servers can open authentication or tools directly.

| State                          | Preview                                                                                                   |
| ------------------------------ | --------------------------------------------------------------------------------------------------------- |
| CreateAndContinue              | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--create-and-continue)               |
| DirectAuthentication           | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--direct-authentication)             |
| UnsavedChanges                 | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--unsaved-changes)                   |
| BackPreservesDraft             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--back-preserves-draft)              |
| ChangedUrlResetsAuthentication | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--changed-url-resets-authentication) |
| SaveDetailsOnPage      | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--save-details-on-page)      |

## Authentication

| State                        | Preview                                                                                                      |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| OAuthAutomatic               | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--o-auth-automatic)                 |
| OAuthOwnClient               | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--o-auth-own-client)                |
| OAuthSavedMasked             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--o-auth-saved-masked)              |
| OAuthManualEndpoints         | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--o-auth-manual-endpoints)          |
| DiscoveryLoading             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--discovery-loading)                |
| DiscoveryMissing             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--discovery-missing)                |
| DiscoveryUnreachable         | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--discovery-unreachable)            |
| DiscoveryUnsupported         | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--discovery-unsupported)            |
| DiscoveryRetry               | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--discovery-retry)                  |
| ApiPersonal                  | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--api-personal)                     |
| ApiShared                    | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--api-shared)                       |
| ApiCustomHeaders             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--api-custom-headers)               |
| NoAuthentication             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--no-authentication)                |
| PassThrough                  | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--pass-through)                     |
| SettingsLoading              | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--settings-loading)                 |
| SettingsLoadError            | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--settings-load-error)              |
| ClientValidation             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--client-validation)                |
| Saving                       | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--saving)                           |
| SaveError                    | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--save-error)                       |
| RegistrationError            | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--registration-error)               |
| ToolDiscoveryError           | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--tool-discovery-error)             |
| SharedHeaderValidation       | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--shared-header-validation)         |
| ChangeMethodAfterOAuthError  | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--change-method-after-o-auth-error) |
| SharedToPersonalClearsSecret | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--shared-to-personal-clears-secret) |
| PassThroughUnavailable       | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--pass-through-unavailable)         |
| AdvancedConnectionSettings   | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-authentication--advanced-connection-settings)     |

## Server details

| State                  | Preview                                                                                               |
| ---------------------- | ----------------------------------------------------------------------------------------------------- |
| NewPublic              | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--new-public)                |
| CraftAvailable         | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--craft-available)           |
| CraftDisabledForServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--craft-disabled-for-server) |
| EditPublic             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--edit-public)               |
| UserGroups             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--user-groups)               |
| FiftyGroups            | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--fifty-groups)              |
| RetainedUserGrants     | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--retained-user-grants)      |
| ScopedManager          | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--scoped-manager)            |
| CommunityPlan          | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--community-plan)            |
| GroupsLoading          | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--groups-loading)            |
| GroupsError            | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--groups-error)              |
| InvalidUrl             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--invalid-url)               |
| Saving                 | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--saving)                    |
| SaveError              | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--save-error)                |
| RequiredName           | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-server-details--required-name)             |

## Fixture behavior

- Discovery loading and saving remain pending for inspection.
- Discovery retry fails once, then returns supported metadata.
- Error stories run the real submit handler and retain the form.
- Group stories use 55 available groups, including a case with 50 selected groups.
- Scoped manager and Community plan stories use real permission and tier hooks.
- Craft stories show availability switches on the server page.
- Validation stories focus and blur real fields.
- Header, authentication tabs, setup tabs, credential scopes, and advanced controls remain interactive.
- Configure authentication saves details and opens authentication without closing the dialog.
- Save Changes keeps the server configuration tab open.
- Closing a dirty page asks before discarding changes. Cancel preserves both page drafts.
- Completing authentication opens the server page, with tools below its settings.
- Tool switches and Craft policies remain drafts until Save Changes.
- Tool fixtures retain saved switches and policies across navigation.
- The default-chat availability switch retains its saved value.

## Tools

| State | Preview |
| --- | --- |
| AvailableTools | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--available-tools) |
| CraftPermissions | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--craft-permissions) |
| Loading | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--loading) |
| LoadError | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--load-error) |
| Empty | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--empty) |
| EmptyCraftPermissions | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--empty-craft-permissions) |
| ReadOnly | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--read-only) |
| SaveChanges | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--save-changes) |
| SaveError | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--save-error) |
| Saving | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--saving) |
| UnsavedChanges | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-tools--unsaved-changes) |

The setup-flow **AuthenticationOpensDetailPage** story checks the transition to the server page.
The server-details **DefaultChatDisabled** story checks saving default-chat availability.

## Server page

The `Apps/Actions/MCP Server Page` group covers Ready, SetupIncomplete,
WithoutCraft, Loading, LoadError, ReadOnly, EditServer, EditAuthentication,
AvailabilityPersists, PartialDefaultChatSelection, ScopedManagerDefaultChatReadOnly,
DraftsSurviveTabChanges, and UnsavedServerChanges.

[Open the server page](http://localhost:6006/?path=/story/apps-actions-mcp-server-page--ready).
Tools stories use the same full page. The wizard retains two pages. Existing servers use inline Server configuration,
Authentication, and Tools tabs. Drafts remain when users change tabs. All API requests use local
fixtures, including availability writes.

Default Chat fixtures store the default assistant's `tool_ids`, using the same
GET and PATCH routes as Chat Preferences. No server availability flag is mocked.
