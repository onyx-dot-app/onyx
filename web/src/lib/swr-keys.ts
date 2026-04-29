/**
 * Centralized SWR cache key registry.
 *
 * All useSWR calls and mutate() calls should reference these constants
 * instead of inline strings to prevent typos and make key usage greppable.
 *
 * For dynamic keys (e.g. per-ID endpoints), use the builder functions.
 */
export const SWR_KEYS = {
  // ── User ──────────────────────────────────────────────────────────────────
  me: "/api/me",

  // ── Health / Version ──────────────────────────────────────────────────────
  health: "/api/health",
  version: "/api/version",

  // ── Settings ──────────────────────────────────────────────────────────────
  settings: "/api/settings",
  enterpriseSettings: "/api/enterprise-settings",
  customAnalyticsScript: "/api/enterprise-settings/custom-analytics-script",
  authType: "/api/auth/type",

  // ── Agents / Personas ─────────────────────────────────────────────────────
  personas: "/api/persona",
  persona: (id: number) => `/api/persona/${id}`,
  agentPreferences: "/api/user/assistant/preferences",
  defaultAssistantConfig: "/api/admin/default-assistant/configuration",
  personaLabels: "/api/persona/labels",

  // ── LLM Providers ─────────────────────────────────────────────────────────
  llmProviders: "/api/llm/provider",
  llmProvidersForPersona: (personaId: number) =>
    `/api/llm/persona/${personaId}/providers`,
  adminLlmProviders: "/api/admin/llm/provider",
  llmProvidersWithImageGen: "/api/admin/llm/provider?include_image_gen=true",
  customProviderNames: "/api/admin/llm/custom-provider-names",
  wellKnownLlmProviders: "/api/admin/llm/built-in/options",
  wellKnownLlmProvider: (providerEndpoint: string) =>
    `/api/admin/llm/built-in/options/${providerEndpoint}`,

  // ── Image Generation ──────────────────────────────────────────────────────
  imageGenConfig: "/api/admin/image-generation/config",

  // ── Documents ─────────────────────────────────────────────────────────────
  documentSets: "/api/manage/document-set",
  documentSetsEditable: "/api/manage/document-set?get_editable=true",
  tags: "/api/query/valid-tags",
  connectorStatus: "/api/manage/connector-status",

  // ── Credentials & Connectors ──────────────────────────────────────────────
  adminCredentials: "/api/manage/admin/credential",
  indexingStatus: "/api/manage/admin/connector/indexing-status",
  adminConnectorStatus: "/api/manage/admin/connector/status",
  federatedConnectors: "/api/federated",

  // ── Google Connectors ─────────────────────────────────────────────────────
  googleConnectorAppCredential: (service: "gmail" | "google-drive") =>
    `/api/manage/admin/connector/${service}/app-credential`,
  googleConnectorServiceAccountKey: (service: "gmail" | "google-drive") =>
    `/api/manage/admin/connector/${service}/service-account-key`,
  googleConnectorCredentials: (service: "gmail" | "google-drive") =>
    `/api/manage/admin/connector/${service}/credentials`,
  googleConnectorPublicCredential: (service: "gmail" | "google-drive") =>
    `/api/manage/admin/connector/${service}/public-credential`,
  googleConnectorServiceAccountCredential: (
    service: "gmail" | "google-drive"
  ) => `/api/manage/admin/connector/${service}/service-account-credential`,

  // ── Search Settings ───────────────────────────────────────────────────────
  currentSearchSettings: "/api/search-settings/get-current-search-settings",
  secondarySearchSettings: "/api/search-settings/get-secondary-search-settings",

  // ── Chat Sessions ─────────────────────────────────────────────────────────
  chatSessions: "/api/chat/get-user-chat-sessions",

  // ── Projects & Files ──────────────────────────────────────────────────────
  userProjects: "/api/user/projects",
  recentFiles: "/api/user/files/recent",
  userPats: "/api/user/pats",
  notifications: "/api/notifications",

  // ── Users ─────────────────────────────────────────────────────────────────
  acceptedUsers: "/api/manage/users/accepted/all",
  invitedUsers: "/api/manage/users/invited",
  // Curator-accessible listing of all users (and optionally service-account
  // entries when `?include_api_keys=true`). Used by group create/edit pages so
  // global curators — who cannot hit the admin-only `/accepted/all` and
  // `/invited` endpoints — can still load the member picker.
  groupMemberCandidates: "/api/manage/users?include_api_keys=true",
  pendingTenantUsers: "/api/tenants/users/pending",
  userCounts: "/api/manage/users/counts",

  // ── API Keys ──────────────────────────────────────────────────────────────
  adminApiKeys: "/api/admin/api-key",

  // ── Groups ────────────────────────────────────────────────────────────────
  adminUserGroups: "/api/manage/admin/user-group",
  shareableGroups: "/api/manage/user-groups/minimal",
  scimToken: "/api/admin/enterprise-settings/scim/token",

  // ── MCP Servers ───────────────────────────────────────────────────────────
  adminMcpServers: "/api/admin/mcp/servers",
  mcpServers: "/api/mcp/servers",

  // ── Tools ─────────────────────────────────────────────────────────────────
  tools: "/api/tool",
  openApiTools: "/api/tool/openapi",
  oauthTokenStatus: "/api/user-oauth-token/status",

  // ── Voice ─────────────────────────────────────────────────────────────────
  voiceProviders: "/api/admin/voice/providers",
  voiceStatus: "/api/voice/status",

  // ── Build (Craft) ─────────────────────────────────────────────────────────
  buildConnectors: "/api/build/connectors",
  buildUserLibraryTree: "/api/build/user-library/tree",
  buildSessionFiles: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/files?path=`,
  buildSessionOutputFiles: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/files?path=outputs`,
  buildSessionWebappInfo: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/webapp-info`,
  buildSessionArtifacts: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/artifacts`,
  buildSessionArtifactFile: (sessionId: string, filePath: string) =>
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
  buildSessionPptxPreview: (sessionId: string, filePath: string) =>
    `/api/build/sessions/${sessionId}/pptx-preview/${filePath}`,

  // ── OpenSearch Migration ──────────────────────────────────────────────────
  opensearchMigrationStatus: "/api/admin/opensearch-migration/status",
  opensearchMigrationRetrieval: "/api/admin/opensearch-migration/retrieval",

  // ── Token Rate Limits ─────────────────────────────────────────────────────
  globalTokenRateLimits: "/api/admin/token-rate-limits/global",
  userTokenRateLimits: "/api/admin/token-rate-limits/users",
  userGroupTokenRateLimits: "/api/admin/token-rate-limits/user-groups",
  userGroupTokenRateLimit: (groupId: number) =>
    `/api/admin/token-rate-limits/user-group/${groupId}`,

  // ── Usage Reports ─────────────────────────────────────────────────────────
  usageReport: "/api/admin/usage-report",

  // ── Web Search ────────────────────────────────────────────────────────────
  webSearchContentProviders: "/api/admin/web-search/content-providers",
  webSearchSearchProviders: "/api/admin/web-search/search-providers",

  // ── Prompt shortcuts ──────────────────────────────────────────────────────
  promptShortcuts: "/api/input_prompt",

  // ── License & Billing ─────────────────────────────────────────────────────
  license: "/api/license",
  billingInformationCloud: "/api/tenants/billing-information",
  billingInformationSelfHosted: "/api/admin/billing/billing-information",

  // ── Admin ─────────────────────────────────────────────────────────────────
  hooks: "/api/admin/hooks",
  hookSpecs: "/api/admin/hooks/specs",

  // ── Slack Bots ────────────────────────────────────────────────────────────
  slackChannels: "/api/manage/admin/slack-app/channel",
  slackBots: "/api/manage/admin/slack-app/bots",
  slackBot: (botId: number) => `/api/manage/admin/slack-app/bots/${botId}`,
  slackBotConfig: (botId: number) =>
    `/api/manage/admin/slack-app/bots/${botId}/config`,

  // ── Standard Answers (EE) ─────────────────────────────────────────────────
  standardAnswerCategories: "/api/manage/admin/standard-answer/category",
  standardAnswers: "/api/manage/admin/standard-answer",

  // ── Query History (EE) ────────────────────────────────────────────────────
  adminChatSessionHistory: "/api/admin/chat-session-history",
  adminChatSession: (id: string) => `/api/admin/chat-session-history/${id}`,

  // ── MCP Server (per-ID) ───────────────────────────────────────────────────
  adminMcpServer: (id: number) => `/api/admin/mcp/servers/${id}`,

  // ── Document Processing ───────────────────────────────────────────────────
  unstructuredApiKeySet: "/api/search-settings/unstructured-api-key-set",

  // ── Connectors ────────────────────────────────────────────────────────────
  connector: "/api/manage/connector",

  // ── Index Attempts ────────────────────────────────────────────────────────
  indexAttemptStageMetrics: (indexAttemptId: number) =>
    `/api/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,
} as const;
