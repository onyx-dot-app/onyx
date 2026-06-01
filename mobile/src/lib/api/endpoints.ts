// Centralized API path registry. Reference these constants instead of inline strings;
// use the builder functions for per-ID keys. These double as TanStack Query keys — a
// URL string (or `[builder(id)]`) IS the query key.
//
// Paths are ROOT-RELATIVE (no `/api` prefix). The mobile client talks to the backend
// directly; the `/api` prefix is a web-only Next.js proxy convention. Any prefix belongs
// in config.baseUrl (set ONYX_API_BASE_URL for a reverse-proxy deployment).
export const API_PATHS = {
  me: "/me",

  health: "/health",
  version: "/version",

  settings: "/settings",
  enterpriseSettings: "/enterprise-settings",
  customAnalyticsScript: "/enterprise-settings/custom-analytics-script",
  authType: "/auth/type",

  personas: "/persona",
  persona: (id: number) => `/persona/${id}`,
  agentPreferences: "/user/assistant/preferences",
  defaultAssistantConfig: "/admin/default-assistant/configuration",
  personaLabels: "/persona/labels",
  adminAgents: "/admin/agents",
  adminPersona: "/admin/persona",

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

  imageGenConfig: "/admin/image-generation/config",

  documentSets: "/manage/document-set",
  documentSetsEditable: "/manage/document-set?get_editable=true",
  tags: "/query/valid-tags",
  connectorStatus: "/manage/connector-status",

  adminCredentials: "/manage/admin/credential",
  indexingStatus: "/manage/admin/connector/indexing-status",
  adminConnectorStatus: "/manage/admin/connector/status",
  federatedConnectors: "/federated",

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

  currentSearchSettings: "/search-settings/get-current-search-settings",
  secondarySearchSettings: "/search-settings/get-secondary-search-settings",
  embeddingProviders: "/admin/embedding/embedding-provider",

  chatSessions: "/chat/get-user-chat-sessions",
  // Full message history for one session (used to hydrate the thread on open).
  getChatSession: (chatSessionId: string) =>
    `/chat/get-chat-session/${chatSessionId}`,

  userProjects: "/user/projects",
  // Create takes the name as a query param (web parity: POST /create?name=).
  createProject: (name: string) =>
    `/user/projects/create?name=${encodeURIComponent(name)}`,
  userProject: (projectId: number) => `/user/projects/${projectId}`,
  projectDetails: (projectId: number) =>
    `/user/projects/${projectId}/details`,
  projectInstructions: (projectId: number) =>
    `/user/projects/${projectId}/instructions`,
  projectFileLink: (projectId: number, fileId: string) =>
    `/user/projects/${projectId}/files/${encodeURIComponent(fileId)}`,
  recentFiles: "/user/files/recent",
  chatFileUpload: "/user/projects/file/upload",
  chatFileStatuses: "/user/projects/file/statuses",
  userPats: "/user/pats",
  notifications: "/notifications",

  acceptedUsers: "/manage/users/accepted/all",
  invitedUsers: "/manage/users/invited",
  // Curator-accessible member picker: global curators can't hit the admin-only
  // /accepted/all + /invited endpoints, so group create/edit reads this instead.
  groupMemberCandidates: "/manage/users?include_api_keys=true",
  pendingTenantUsers: "/tenants/users/pending",
  userCounts: "/manage/users/counts",

  adminApiKeys: "/admin/api-key",

  adminUserGroups: "/manage/admin/user-group",
  shareableGroups: "/manage/user-groups/minimal",
  scimToken: "/admin/enterprise-settings/scim/token",

  adminMcpServers: "/admin/mcp/servers",
  mcpServers: "/mcp/servers",

  adminSkills: "/admin/skills",
  userSkills: "/skills",

  tools: "/tool",
  openApiTools: "/tool/openapi",
  oauthTokenStatus: "/user-oauth-token/status",

  voiceProviders: "/admin/voice/providers",
  voiceStatus: "/voice/status",

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

  globalTokenRateLimits: "/admin/token-rate-limits/global",
  userTokenRateLimits: "/admin/token-rate-limits/users",
  userGroupTokenRateLimits: "/admin/token-rate-limits/user-groups",
  userGroupTokenRateLimit: (groupId: number) =>
    `/admin/token-rate-limits/user-group/${groupId}`,

  usageReport: "/admin/usage-report",

  webSearchContentProviders: "/admin/web-search/content-providers",
  webSearchSearchProviders: "/admin/web-search/search-providers",

  promptShortcuts: "/input_prompt",

  license: "/license",
  billingInformationCloud: "/tenants/billing-information",
  billingInformationSelfHosted: "/admin/billing/billing-information",

  hooks: "/admin/hooks",
  hookSpecs: "/admin/hooks/specs",

  slackChannels: "/manage/admin/slack-app/channel",
  slackBots: "/manage/admin/slack-app/bots",
  slackBot: (botId: number) => `/manage/admin/slack-app/bots/${botId}`,
  slackBotConfig: (botId: number) =>
    `/manage/admin/slack-app/bots/${botId}/config`,

  standardAnswerCategories: "/manage/admin/standard-answer/category",
  standardAnswers: "/manage/admin/standard-answer",

  adminChatSessionHistory: "/admin/chat-session-history",
  adminChatSession: (id: string) => `/admin/chat-session-history/${id}`,

  adminMcpServer: (id: number) => `/admin/mcp/servers/${id}`,

  unstructuredApiKeySet: "/search-settings/unstructured-api-key-set",

  connector: "/manage/connector",

  indexAttemptStageMetrics: (indexAttemptId: number) =>
    `/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,

  // `*Probe` variants are single-row reads that surface the `applicable` flag
  // without paying for a full page; see `useSyncAttemptsPaginatedFetch`.
  ccPairPermissionSyncAttempts: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/permission-sync-attempts`,
  ccPairPermissionSyncAttemptsProbe: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/permission-sync-attempts?page_num=0&page_size=1`,
  ccPairExternalGroupSyncAttempts: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/external-group-sync-attempts`,
  ccPairExternalGroupSyncAttemptsProbe: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/external-group-sync-attempts?page_num=0&page_size=1`,

  // Base key: the page reads paginated variants via `usePaginatedFetch`, but
  // `mutate` against this base invalidates every variant under the same prefix.
  ccPairIndexingErrors: (ccPairId: number) =>
    `/manage/admin/cc-pair/${ccPairId}/errors`,

  // `scheduledTaskRuns` is a base URL — the table appends `?limit=…`/`?cursor=…`.
  // Invalidate with a prefix predicate to refresh every paginated variant at once.
  scheduledTasks: "/build/scheduled-tasks",
  scheduledTask: (taskId: string) => `/build/scheduled-tasks/${taskId}`,
  scheduledTaskRuns: (taskId: string) =>
    `/build/scheduled-tasks/${taskId}/runs`,
  scheduledRunContext: (sessionId: string) =>
    `/build/sessions/${sessionId}/scheduled-run-context`,
} as const;
