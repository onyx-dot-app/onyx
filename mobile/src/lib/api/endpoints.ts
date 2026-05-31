/**
 * Centralized SWR cache key registry.
 *
 * All useSWR calls and mutate() calls should reference these constants
 * instead of inline strings to prevent typos and make key usage greppable.
 *
 * For dynamic keys (e.g. per-ID endpoints), use the builder functions.
 *
 * NOTE: paths are ROOT-RELATIVE (no `/api` prefix). The mobile client talks to the
 * backend directly, which serves routes at root — the `/api` prefix is a web-only
 * Next.js proxy convention. Any prefix belongs in `apiBaseUrl` (config), matching the
 * auth client (e.g. `/auth/mobile/login`). For a reverse-proxy deployment, set
 * ONYX_API_BASE_URL to include the prefix (e.g. https://host/api).
 */
export const SWR_KEYS = {
  // ── User ──────────────────────────────────────────────────────────────────
  me: "/me",

  // ── Health / Version ──────────────────────────────────────────────────────
  health: "/health",
  version: "/version",

  // ── Settings ──────────────────────────────────────────────────────────────
  settings: "/settings",
  enterpriseSettings: "/enterprise-settings",
  customAnalyticsScript: "/enterprise-settings/custom-analytics-script",
  authType: "/auth/type",

  // ── Agents / Personas ─────────────────────────────────────────────────────
  personas: "/persona",
  persona: (id: number) => `/persona/${id}`,
  agentPreferences: "/user/assistant/preferences",
  defaultAssistantConfig: "/admin/default-assistant/configuration",
  personaLabels: "/persona/labels",
  adminAgents: "/admin/agents",
  adminPersona: "/admin/persona",

  // ── LLM Providers ─────────────────────────────────────────────────────────
  llmProviders: "/llm/provider",
  llmProvidersForPersona: (personaId: number) =>
    `/llm/persona/${personaId}/providers`,
  adminLlmProviders: "/admin/llm/provider",
  llmProvidersWithImageGen: "/admin/llm/provider?include_image_gen=true",
  customProviderNames: "/admin/llm/custom-provider-names",
  wellKnownLlmProviders: "/admin/llm/built-in/options",
  wellKnownLlmProvider: (providerEndpoint: string) =>
    `/admin/llm/built-in/options/${providerEndpoint}`,
  llmContextualCost: "/admin/llm/provider-contextual-cost",

  // ── Image Generation ──────────────────────────────────────────────────────
  imageGenConfig: "/admin/image-generation/config",

  // ── Documents ─────────────────────────────────────────────────────────────
  documentSets: "/manage/document-set",
  documentSetsEditable: "/manage/document-set?get_editable=true",
  tags: "/query/valid-tags",
  connectorStatus: "/manage/connector-status",

  // ── Credentials & Connectors ──────────────────────────────────────────────
  adminCredentials: "/manage/admin/credential",
  indexingStatus: "/manage/admin/connector/indexing-status",
  adminConnectorStatus: "/manage/admin/connector/status",
  federatedConnectors: "/federated",

  // ── Google Connectors ─────────────────────────────────────────────────────
  googleConnectorAppCredential: (service: "gmail" | "google-drive") =>
    `/manage/admin/connector/${service}/app-credential`,
  googleConnectorServiceAccountKey: (service: "gmail" | "google-drive") =>
    `/manage/admin/connector/${service}/service-account-key`,
  googleConnectorCredentials: (service: "gmail" | "google-drive") =>
    `/manage/admin/connector/${service}/credentials`,
  googleConnectorPublicCredential: (service: "gmail" | "google-drive") =>
    `/manage/admin/connector/${service}/public-credential`,
  googleConnectorServiceAccountCredential: (
    service: "gmail" | "google-drive"
  ) => `/manage/admin/connector/${service}/service-account-credential`,

  // ── Search Settings ───────────────────────────────────────────────────────
  currentSearchSettings: "/search-settings/get-current-search-settings",
  secondarySearchSettings: "/search-settings/get-secondary-search-settings",
  embeddingProviders: "/admin/embedding/embedding-provider",

  // ── Chat Sessions ─────────────────────────────────────────────────────────
  chatSessions: "/chat/get-user-chat-sessions",

  // ── Projects & Files ──────────────────────────────────────────────────────
  userProjects: "/user/projects",
  recentFiles: "/user/files/recent",
  userPats: "/user/pats",
  notifications: "/notifications",

  // ── Users ─────────────────────────────────────────────────────────────────
  acceptedUsers: "/manage/users/accepted/all",
  invitedUsers: "/manage/users/invited",
  // Curator-accessible listing of all users (and optionally service-account
  // entries when `?include_api_keys=true`). Used by group create/edit pages so
  // global curators — who cannot hit the admin-only `/accepted/all` and
  // `/invited` endpoints — can still load the member picker.
  groupMemberCandidates: "/manage/users?include_api_keys=true",
  pendingTenantUsers: "/tenants/users/pending",
  userCounts: "/manage/users/counts",

  // ── API Keys ──────────────────────────────────────────────────────────────
  adminApiKeys: "/admin/api-key",

  // ── Groups ────────────────────────────────────────────────────────────────
  adminUserGroups: "/manage/admin/user-group",
  shareableGroups: "/manage/user-groups/minimal",
  scimToken: "/admin/enterprise-settings/scim/token",

  // ── MCP Servers ───────────────────────────────────────────────────────────
  adminMcpServers: "/admin/mcp/servers",
  mcpServers: "/mcp/servers",

  // ── Skills ────────────────────────────────────────────────────────────────
  adminSkills: "/admin/skills",
  userSkills: "/skills",

  // ── Tools ─────────────────────────────────────────────────────────────────
  tools: "/tool",
  openApiTools: "/tool/openapi",
  oauthTokenStatus: "/user-oauth-token/status",

  // ── Voice ─────────────────────────────────────────────────────────────────
  voiceProviders: "/admin/voice/providers",
  voiceStatus: "/voice/status",

  // ── Build (Craft) ─────────────────────────────────────────────────────────
  buildUserLibraryTree: "/build/user-library/tree",
  buildSessionFiles: (sessionId: string) =>
    `/build/sessions/${sessionId}/files?path=`,
  buildSessionOutputFiles: (sessionId: string) =>
    `/build/sessions/${sessionId}/files?path=outputs`,
  buildSessionWebappInfo: (sessionId: string) =>
    `/build/sessions/${sessionId}/webapp-info`,
  buildSessionArtifacts: (sessionId: string) =>
    `/build/sessions/${sessionId}/artifacts`,
  buildSessionArtifactFile: (sessionId: string, filePath: string) =>
    `/build/sessions/${sessionId}/artifacts/${filePath}`,
  buildSessionPptxPreview: (sessionId: string, filePath: string) =>
    `/build/sessions/${sessionId}/pptx-preview/${filePath}`,
  buildExternalApps: "/build/apps",
  buildExternalAppsAdmin: "/build/admin/apps",
  buildExternalAppsBuiltInOptions: "/build/admin/apps/built-in/options",
  buildSessionLiveApprovals: (sessionId: string) =>
    `/build/approvals/sessions/${sessionId}/live`,

  // ── Token Rate Limits ─────────────────────────────────────────────────────
  globalTokenRateLimits: "/admin/token-rate-limits/global",
  userTokenRateLimits: "/admin/token-rate-limits/users",
  userGroupTokenRateLimits: "/admin/token-rate-limits/user-groups",
  userGroupTokenRateLimit: (groupId: number) =>
    `/admin/token-rate-limits/user-group/${groupId}`,

  // ── Usage Reports ─────────────────────────────────────────────────────────
  usageReport: "/admin/usage-report",

  // ── Web Search ────────────────────────────────────────────────────────────
  webSearchContentProviders: "/admin/web-search/content-providers",
  webSearchSearchProviders: "/admin/web-search/search-providers",

  // ── Prompt shortcuts ──────────────────────────────────────────────────────
  promptShortcuts: "/input_prompt",

  // ── License & Billing ─────────────────────────────────────────────────────
  license: "/license",
  billingInformationCloud: "/tenants/billing-information",
  billingInformationSelfHosted: "/admin/billing/billing-information",

  // ── Admin ─────────────────────────────────────────────────────────────────
  hooks: "/admin/hooks",
  hookSpecs: "/admin/hooks/specs",

  // ── Slack Bots ────────────────────────────────────────────────────────────
  slackChannels: "/manage/admin/slack-app/channel",
  slackBots: "/manage/admin/slack-app/bots",
  slackBot: (botId: number) => `/manage/admin/slack-app/bots/${botId}`,
  slackBotConfig: (botId: number) =>
    `/manage/admin/slack-app/bots/${botId}/config`,

  // ── Standard Answers (EE) ─────────────────────────────────────────────────
  standardAnswerCategories: "/manage/admin/standard-answer/category",
  standardAnswers: "/manage/admin/standard-answer",

  // ── Query History (EE) ────────────────────────────────────────────────────
  adminChatSessionHistory: "/admin/chat-session-history",
  adminChatSession: (id: string) => `/admin/chat-session-history/${id}`,

  // ── MCP Server (per-ID) ───────────────────────────────────────────────────
  adminMcpServer: (id: number) => `/admin/mcp/servers/${id}`,

  // ── Document Processing ───────────────────────────────────────────────────
  unstructuredApiKeySet: "/search-settings/unstructured-api-key-set",

  // ── Connectors ────────────────────────────────────────────────────────────
  connector: "/manage/connector",

  // ── Index Attempts ────────────────────────────────────────────────────────
  indexAttemptStageMetrics: (indexAttemptId: number) =>
    `/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,

  // ── CC-Pair Sync Attempts ─────────────────────────────────────────────────
  // The `*Probe` variants are single-row reads used to surface the
  // `applicable` flag without paying for a full page; see
  // `useSyncAttemptsPaginatedFetch`.
  ccPairPermissionSyncAttempts: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/permission-sync-attempts`,
  ccPairPermissionSyncAttemptsProbe: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/permission-sync-attempts?page_num=0&page_size=1`,
  ccPairExternalGroupSyncAttempts: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/external-group-sync-attempts`,
  ccPairExternalGroupSyncAttemptsProbe: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/external-group-sync-attempts?page_num=0&page_size=1`,

  // ── Indexing Errors ───────────────────────────────────────────────────────
  // Base key for the per-cc-pair errors endpoint. The page also reads
  // paginated variants via `usePaginatedFetch`, but `mutate` against
  // this base key invalidates every variant under the same prefix.
  ccPairIndexingErrors: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/errors`,

  // ── Scheduled Tasks (Craft) ───────────────────────────────────────────────
  // `scheduledTaskRuns` is a base URL — the run-history table appends
  // `?limit=…` / `?cursor=…` for pagination. Invalidate from elsewhere with
  // a prefix predicate so every paginated variant gets refreshed at once.
  scheduledTasks: "/build/scheduled-tasks",
  scheduledTask: (taskId: string) => `/build/scheduled-tasks/${taskId}`,
  scheduledTaskRuns: (taskId: string) =>
    `/build/scheduled-tasks/${taskId}/runs`,
  scheduledRunContext: (sessionId: string) =>
    `/build/sessions/${sessionId}/scheduled-run-context`,
} as const;
