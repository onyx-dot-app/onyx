/**
 * Centralized SWR cache key registry.
 *
 * All useSWR calls and mutate() calls should reference these constants
 * instead of inline strings to prevent typos and make key usage greppable.
 *
 * For dynamic keys (e.g. per-ID endpoints), use the builder functions.
 */
import type {
  CCPairRunLevel,
  CCPairRunsQuery,
  CCPairThroughputWindow,
  IndexingConnectorsQuery,
} from "@/lib/connectors/types";

/** The query string a runs feed takes, for one pair or the fleet. */
function runsQueryParams(query: CCPairRunsQuery): string {
  const params = new URLSearchParams({
    page_num: String(query.pageNum),
    page_size: String(query.pageSize),
  });
  if (query.since !== null) params.set("since", query.since);
  if (query.until !== null) params.set("until", query.until);
  for (const kind of query.kinds ?? []) params.append("kinds", kind);
  for (const group of query.statusGroups ?? []) {
    params.append("status_groups", group);
  }
  if (query.q) params.set("q", query.q);
  if (query.errors !== null) params.set("errors", query.errors);
  if (query.superseded !== null) {
    params.set("superseded", String(query.superseded));
  }
  if (query.resolved !== null) {
    params.set("resolved", String(query.resolved));
  }
  return params.toString();
}

function resolvableCountParams(
  level: CCPairRunLevel | null,
  q: string,
  since: string | null,
  until: string | null
): string {
  const params = new URLSearchParams();
  if (level !== null) params.set("level", level);
  if (q) params.set("q", q);
  if (since) params.set("since", since);
  if (until) params.set("until", until);
  return params.toString();
}

export const SWR_KEYS = {
  // ── User ──────────────────────────────────────────────────────────────────
  me: "/api/me",

  // ── Health / Version ──────────────────────────────────────────────────────
  health: "/api/health",
  opensearchResourceHealth: "/api/manage/admin/opensearch-health",
  version: "/api/version",

  // ── Settings ──────────────────────────────────────────────────────────────
  settings: "/api/settings",
  enterpriseSettings: "/api/enterprise-settings",
  customAnalyticsScript: "/api/enterprise-settings/custom-analytics-script",
  authType: "/api/auth/type",
  adminSecuritySettings: "/api/admin/security",
  adminSecurityPinnedFields: "/api/admin/security/pinned-fields",
  incognitoAvailability: "/api/chat/incognito-availability",
  adminSsoProviders: "/api/admin/sso/provider",
  adminSsoProviderTypes: "/api/admin/sso/provider-type",
  adminSsoDomains: "/api/admin/sso/domain",
  // Cache key for the POST /records lookup, keyed by the domains being configured.
  adminSsoDomainRecords: (domains: string[]) => [
    "sso-domain-records",
    ...domains,
  ],

  // ── Agents ────────────────────────────────────────────────────────────────
  agents: "/api/persona",
  agent: (agentId: number) => `/api/persona/${agentId}`,
  defaultAssistantConfig: "/api/admin/default-assistant/configuration",
  agentLabels: "/api/persona/labels",
  adminAgentLabel: (labelId: number) => `/api/admin/persona/label/${labelId}`,
  adminAgents: "/api/admin/agents",
  adminPersona: "/api/admin/persona",

  // ── LLM Providers ─────────────────────────────────────────────────────────
  llmProviders: "/api/llm/provider",
  llmProvidersForAgent: (agentId: number) =>
    `/api/llm/persona/${agentId}/providers`,
  llmProviderModels: (providerId: number) =>
    `/api/llm/provider/${providerId}/models`,
  adminLlmProviders: "/api/admin/llm/provider",
  decisionModel: "/api/admin/llm/decision-model",
  adminLlmProvidersPaged: "/api/admin/llm/provider?page_models=true",
  adminLlmProvider: (providerId: number) =>
    `/api/admin/llm/provider/${providerId}`,
  llmRouterModels: "/api/admin/llm/router-models",
  customProviderNames: "/api/admin/llm/custom-provider-names",
  wellKnownLlmProviders: "/api/admin/llm/built-in/options",
  wellKnownLlmProvider: (providerEndpoint: string) =>
    `/api/admin/llm/built-in/options/${providerEndpoint}`,
  llmContextualCost: "/api/admin/llm/provider-contextual-cost",
  userUsage: "/api/user/usage",
  costOverrides: "/api/admin/cost-overrides",
  adminUsageExport: "/api/admin/usage/export",
  adminSystemUsage: "/api/admin/usage/system",
  adminUsageReset: "/api/admin/usage/reset",

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
  connectorGroupRestrictions: "/api/manage/connector-group-restrictions",
  // The add-connector form's check session, client state shared by the
  // checks card, the configuration lock and the Connect button.
  connectorCheckSession: (source: string) => [
    "connector-check-session",
    source,
  ],
  // The draft credential a check run saved the add-connector form's typed
  // account as. Client state.
  connectorDraftCredential: (source: string) => [
    "connector-draft-credential",
    source,
  ],
  // The checks a run would hold for an unsaved connector form (a POST).
  connectorCheckPlan: (
    source: string,
    accessType: string | null,
    form: string
  ) => ["connector-check-plan", source, accessType, form],
  // One capability-check run for an unsaved connector form.
  connectorCheckRun: (runId: string) =>
    `/api/manage/admin/connector-checks/runs/${runId}`,

  // ── Google Connectors ─────────────────────────────────────────────────────
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
  reindexProgress: "/api/search-settings/reindex-progress",
  reindexErrors: "/api/search-settings/reindex-errors",
  ccPairIdsBackfillProgress:
    "/api/search-settings/cc-pair-ids-backfill-progress",
  embeddingProviders: "/api/admin/embedding/embedding-provider",

  // ── Chat Sessions ─────────────────────────────────────────────────────────
  chatSessions: "/api/chat/get-user-chat-sessions",
  chatSearch: "/api/chat/search",

  // ── Projects & Files ──────────────────────────────────────────────────────
  userProjects: "/api/user/projects",
  recentFiles: "/api/user/files/recent",
  userPats: "/api/user/pats",
  oauthProviderGrants: "/api/oauth-provider/grants",
  oauthProviderConsent: (requestId: string): string =>
    `/api/oauth-provider/consent?request=${encodeURIComponent(requestId)}`,
  userPatScopes: "/api/user/pats/scopes",
  notifications: "/api/notifications",
  notificationsSummary: "/api/notifications/summary",
  notificationsPage: (pageNum: number, pageSize: number) => {
    const params = new URLSearchParams({
      page_num: pageNum.toString(),
      page_size: pageSize.toString(),
    });
    return `/api/notifications?${params.toString()}`;
  },
  notificationsBySeverity: (minSeverity: string, pageSize: number) => {
    const params = new URLSearchParams({
      min_severity: minSeverity,
      page_size: pageSize.toString(),
    });
    return `/api/notifications?${params.toString()}`;
  },

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
  adminUserGroupsWithDefault:
    "/api/manage/admin/user-group?include_default=true",
  shareableGroups: "/api/manage/user-groups/minimal",
  userGroupPermissions: (groupId: number) =>
    `/api/manage/admin/user-group/${groupId}/permissions`,
  permissionRegistry: "/api/manage/admin/permissions/registry",
  scimToken: "/api/admin/enterprise-settings/scim/token",

  // ── MCP Servers ───────────────────────────────────────────────────────────
  adminMcpServers: "/api/admin/mcp/servers",
  adminMcpServerToolSnapshots: (serverId: number) =>
    `/api/admin/mcp/server/${serverId}/tools/snapshots?source=db`,
  mcpServers: "/api/mcp/servers",
  mcpServersCraft: "/api/mcp/servers/craft",
  agentMcpServers: (agentId: number) => `/api/mcp/servers/persona/${agentId}`,

  // ── Skills ────────────────────────────────────────────────────────────────
  userSkills: "/api/skills",
  userSkillPreview: (skillId: string) => `/api/skills/${skillId}/preview`,
  editableSkill: (skillId: string) => `/api/skills/custom/${skillId}/edit`,

  // ── Tools ─────────────────────────────────────────────────────────────────
  tools: "/api/tool",
  openApiTools: "/api/tool/openapi",
  oauthTokenStatus: "/api/user-oauth-token/status",
  adminOAuthTestClaims: "/api/admin/oauth-test/claims",

  // ── Voice ─────────────────────────────────────────────────────────────────
  voiceProviders: "/api/admin/voice/providers",
  voiceStatus: "/api/voice/status",

  // ── Build (Craft) ─────────────────────────────────────────────────────────
  buildUserLibraryTree: "/api/build/user-library/tree",
  buildSessionFiles: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/files?path=`,
  // Recursive workspace discovery aggregates directory responses, not an endpoint.
  buildSessionWorkspaceInventory: (sessionId: string) => [
    "craft-workspace-inventory",
    sessionId,
  ],
  buildSessionWebappInfo: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/webapp-info`,
  buildSessionArtifacts: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/artifacts`,
  buildSessionOutputCards: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/output-cards`,
  buildSessionArtifactFile: (sessionId: string, filePath: string) =>
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
  buildSessionOutputThumbnail: (sessionId: string, filePath: string) =>
    `craft-output-thumbnail:${sessionId}:${filePath}`,
  buildSessionPptxPreview: (sessionId: string, filePath: string) =>
    `/api/build/sessions/${sessionId}/pptx-preview/${filePath}`,
  buildExternalApps: "/api/build/apps",
  buildExternalAppsAdmin: "/api/build/admin/apps",
  buildExternalAppsBuiltInOptions: "/api/build/admin/apps/built-in/options",
  buildBaseInstructions: "/api/build/admin/base-instructions",
  buildSessionApprovalStatus: (sessionId: string) =>
    `/api/build/approvals/sessions/${sessionId}/status`,
  buildSessionApprovals: (sessionId: string) =>
    `/api/build/approvals/sessions/${sessionId}`,

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

  // ── Tracing ───────────────────────────────────────────────────────────────
  tracingProviders: "/api/admin/tracing/providers",

  // ── Prompt shortcuts ──────────────────────────────────────────────────────
  promptShortcuts: "/api/input_prompt",

  // ── Admin Banner ──────────────────────────────────────────────────────────
  adminBanner: "/api/admin/banner",

  // ── License & Billing ─────────────────────────────────────────────────────
  license: "/api/license",
  billingInformationCloud: "/api/tenants/billing-information",
  billingInformationSelfHosted: "/api/admin/billing/billing-information",

  // ── Admin ─────────────────────────────────────────────────────────────────
  hooks: "/api/admin/hooks",
  hookSpecs: "/api/admin/hooks/specs",
  logExportStatus: (exportId: string) => `/api/admin/log-export/${exportId}`,

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
  adminMcpOAuthDiscovery: (id: number) =>
    ["admin-mcp-oauth-discovery", id] as const,

  // ── Document Processing ───────────────────────────────────────────────────
  unstructuredApiKeySet: "/api/search-settings/unstructured-api-key-set",

  // ── Connectors ────────────────────────────────────────────────────────────
  connector: "/api/manage/connector",
  connectorOAuthDetails: (source: string) =>
    `/api/connector/oauth/details/${source}`,
  // Credentials of one source the caller may attach.
  similarCredentials: (source: string) =>
    `/api/manage/admin/similar-credentials/${source}`,
  // Every stored capability report of one source's credentials.
  credentialCheckReports: (source: string) =>
    `/api/manage/admin/credential/capability-reports?source=${source}`,
  // Every file-list page of one connector starts with this, so `mutate` can match them all.
  connectorFilesPrefix: (connectorId: number) =>
    `/api/manage/admin/connector/${connectorId}/files?`,
  connectorFiles: (connectorId: number, pageNum: number, pageSize: number) =>
    `${SWR_KEYS.connectorFilesPrefix(connectorId)}page_num=${pageNum}&page_size=${pageSize}`,

  // ── CC-Pairs ──────────────────────────────────────────────────────────────
  ccPair: (ccPairId: string | number) =>
    `/api/manage/admin/cc-pair/${ccPairId}`,

  // ── Index Attempts ────────────────────────────────────────────────────────
  ccPairLatestIndexAttempt: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/index-attempts?page_num=0&page_size=1`,
  // Every runs feed query of one pair starts with this, so `mutate` can match them all.
  ccPairRunsPrefix: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/runs?`,
  ccPairRuns: (ccPairId: number, query: CCPairRunsQuery) =>
    `${SWR_KEYS.ccPairRunsPrefix(ccPairId)}${runsQueryParams(query)}`,
  ccPairResolvableRunsCountPrefix: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/runs/resolvable-count?`,
  ccPairResolvableRunsCount: (
    ccPairId: number,
    level: CCPairRunLevel | null,
    q: string,
    since: string | null,
    until: string | null
  ) =>
    `${SWR_KEYS.ccPairResolvableRunsCountPrefix(ccPairId)}${resolvableCountParams(level, q, since, until)}`,
  ccPairThroughput: (ccPairId: number, window: CCPairThroughputWindow) =>
    `/api/manage/admin/cc-pair/${ccPairId}/throughput?window=${window}`,

  // ── Index Monitoring ──────────────────────────────────────────────────────
  // The indexing status page's fleet-wide reads, over every readable pair.
  indexMonitoringOverview: (window: CCPairThroughputWindow) =>
    `/api/manage/admin/index-monitoring/overview?window=${window}`,
  // Every connector list query starts with this, so `mutate` can match them all.
  indexMonitoringConnectorsPrefix:
    "/api/manage/admin/index-monitoring/connectors?",
  indexMonitoringConnectors: (query: IndexingConnectorsQuery) => {
    const params = new URLSearchParams({
      page_num: String(query.pageNum),
      page_size: String(query.pageSize),
    });
    if (query.q) params.set("q", query.q);
    if (query.status !== null) params.set("status", query.status);
    return `${SWR_KEYS.indexMonitoringConnectorsPrefix}${params.toString()}`;
  },
  // Every fleet runs feed query starts with this, so `mutate` can match them all.
  indexMonitoringRunsPrefix: "/api/manage/admin/index-monitoring/runs?",
  indexMonitoringResolvableRunsCountPrefix:
    "/api/manage/admin/index-monitoring/runs/resolvable-count?",
  indexMonitoringResolvableRunsCount: (
    level: CCPairRunLevel | null,
    q: string,
    since: string | null,
    until: string | null
  ) =>
    `${SWR_KEYS.indexMonitoringResolvableRunsCountPrefix}${resolvableCountParams(level, q, since, until)}`,
  indexMonitoringRuns: (query: CCPairRunsQuery) =>
    `${SWR_KEYS.indexMonitoringRunsPrefix}${runsQueryParams(query)}`,
  indexAttemptStageMetrics: (indexAttemptId: number) =>
    `/api/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,

  ccPairHierarchyBreakdown: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/hierarchy-breakdown`,
  ccPairDataAccess: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/data-access`,
  ccPairManageAccess: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/manage-access`,

  // ── Indexing Errors ───────────────────────────────────────────────────────
  // Base key for the per-cc-pair errors endpoint. The page also reads
  // paginated variants via `usePaginatedFetch`, but `mutate` against
  // this base key invalidates every variant under the same prefix.
  ccPairIndexingErrors: (ccPairId: number) =>
    `/api/manage/admin/cc-pair/${ccPairId}/errors`,
  // One attempt's open errors, searched by message or document id.
  ccPairAttemptErrors: (
    ccPairId: number,
    query: {
      indexAttemptId: number;
      q: string;
      pageNum: number;
      pageSize: number;
    }
  ) => {
    const params = new URLSearchParams({
      index_attempt_id: String(query.indexAttemptId),
      page_num: String(query.pageNum),
      page_size: String(query.pageSize),
      include_resolved: "false",
    });
    if (query.q) params.set("q", query.q);
    return `/api/manage/admin/cc-pair/${ccPairId}/errors?${params.toString()}`;
  },

  // ── Scheduled Tasks (Craft) ───────────────────────────────────────────────
  // `scheduledTaskRuns` is a base URL — the run-history table appends
  // `?limit=…` / `?cursor=…` for pagination. Invalidate from elsewhere with
  // a prefix predicate so every paginated variant gets refreshed at once.
  personalActionPolicies: "/api/build/action-policies",
  appActionPolicies: (
    kind: "external_app" | "mcp_server",
    targetId: number,
    admin = false
  ) => `/api/build/${admin ? "admin/" : ""}action-policies/${kind}/${targetId}`,
  taskActionPolicies: (taskId: string) =>
    `/api/build/scheduled-tasks/${taskId}/action-policies`,
  scheduledTasks: "/api/build/scheduled-tasks",
  scheduledTask: (taskId: string) => `/api/build/scheduled-tasks/${taskId}`,
  scheduledTaskRuns: (taskId: string) =>
    `/api/build/scheduled-tasks/${taskId}/runs`,
  scheduledRunContext: (sessionId: string) =>
    `/api/build/sessions/${sessionId}/scheduled-run-context`,
} as const;
