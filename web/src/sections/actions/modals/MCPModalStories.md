# MCP page and editor story inventory

These stories render the setup modal and saved editors. Each story uses an isolated SWR cache and local API responses.
API writes are simulated. OAuth never redirects to a provider. Unhandled API paths return a local error.

These integration previews include the production data hooks and permission checks, with deterministic network fixtures.

Run `bun run storybook` from `web/`. The links below use its default port.
Use **Reopen preview** to reset form state. Reload the story to reset network fixtures.

## Multi-page setup

The creation modal has Server and Connection steps without a timeline. Server contains name and URL inputs.
After 700 milliseconds without another URL edit, the modal checks the endpoint and shows its result.
Continue opens Connection without saving. Connection contains authentication and access.
Back preserves drafts. Connect validates the local draft before creating and authenticating the server.
Public and OAuth servers start with detected defaults. Unknown authentication requires a choice. Failed checks offer retry and manual setup.
Blocked destinations have no manual bypass. Saved servers use the detail modal's configuration, authentication, and tools tabs.
Saved editor stories load their existing server before mounting the form. Creation stories use the production setup modal.
A changed URL clears authentication for the previous destination. Explicit OAuth setup choices survive authentication-method changes.

| State                          | Preview                                                                                                   |
| ------------------------------ | --------------------------------------------------------------------------------------------------------- |
| UrlOnly | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--url-only) |
| CreateAndContinue              | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--create-and-continue)               |
| PublicDetected | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--public-detected) |
| PublicServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--public-server) |
| OAuthDetected | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--o-auth-detected) |
| OAuthServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--o-auth-server) |
| FinalDetails | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--final-details) |
| OAuthOwnClient | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--o-auth-own-client) |
| ManualAuthentication | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--manual-authentication) |
| UnreachableServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--unreachable-server) |
| BlockedServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--blocked-server) |
| CheckingServer | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--checking-server) |
| DetectingAuthentication | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--detecting-authentication) |
| ScopedManager | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--scoped-manager) |
| SaveError | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--save-error) |
| CancelDiscardsDraft | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--cancel-discards-draft) |
| BackPreservesDraft             | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--back-preserves-draft)              |
| ChangedUrlResetsAuthentication | [Open](http://localhost:6006/?path=/story/apps-actions-mcp-setup-flow--changed-url-resets-authentication) |

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
- Page navigation, authentication dropdowns, OAuth radio choices, credential scope, and Advanced remain interactive.
- Continue opens Connection without creating a server.
- Connect creates one server and retains its ID if authentication or tool discovery fails.
- Save Changes keeps the server configuration tab open.
- Creation closes and discards drafts without confirmation. Existing edit pages retain their guards. Back preserves both step drafts for the same URL.
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

The setup modal integration test checks successful completion and its saved server callback.
The server-details **DefaultChatDisabled** story checks saving default-chat availability.

## Server page

The `Apps/Actions/MCP Server Page` group covers Ready, SetupIncomplete,
WithoutCraft, Loading, LoadError, ReadOnly, EditServer, EditAuthentication,
AvailabilityPersists, PartialDefaultChatSelection, ScopedManagerDefaultChatReadOnly,
DraftsSurviveTabChanges, and UnsavedServerChanges.

[Open the server page](http://localhost:6006/?path=/story/apps-actions-mcp-server-page--ready).
Tools stories use the same full page. New setup uses a compact modal with two steps. Existing servers use inline Server configuration,
Authentication, and Tools tabs. Drafts remain when users change tabs. All API requests use local
fixtures, including availability writes.

Default Chat fixtures store the default assistant's `tool_ids`, using the same
GET and PATCH routes as Chat Preferences. No server availability flag is mocked.
