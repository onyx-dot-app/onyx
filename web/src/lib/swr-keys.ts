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

  // ── LLM Providers ─────────────────────────────────────────────────────────
  llmProviders: "/api/llm/provider",
  llmProvidersForPersona: (personaId: number) =>
    `/api/llm/persona/${personaId}/providers`,
  adminLlmProviders: "/api/admin/llm/provider",
  wellKnownLlmProviders: "/api/admin/llm/built-in/options",
  wellKnownLlmProvider: (providerEndpoint: string) =>
    `/api/admin/llm/built-in/options/${providerEndpoint}`,

  // ── Documents ─────────────────────────────────────────────────────────────
  documentSets: "/api/manage/document-set",
  tags: "/api/query/valid-tags",
  connectorStatus: "/api/manage/connector-status",

  // ── Chat Sessions ─────────────────────────────────────────────────────────
  chatSessions: "/api/chat/get-user-chat-sessions",

  // ── Projects & Files ──────────────────────────────────────────────────────
  userProjects: "/api/user/projects",
  recentFiles: "/api/user/files/recent",

  // ── Tools ─────────────────────────────────────────────────────────────────
  tools: "/api/tool",
  oauthTokenStatus: "/api/user-oauth-token/status",

  // ── Voice ─────────────────────────────────────────────────────────────────
  voiceProviders: "/api/admin/voice/providers",
  voiceStatus: "/api/voice/status",

  // ── Prompt shortcuts ──────────────────────────────────────────────────────
  promptShortcuts: "/api/input_prompt",

  // ── License & Billing ─────────────────────────────────────────────────────
  license: "/api/license",
  billingInformationCloud: "/api/tenants/billing-information",
  billingInformationSelfHosted: "/api/admin/billing/billing-information",

  // ── Admin ─────────────────────────────────────────────────────────────────
  hooks: "/api/admin/hooks",
  hookSpecs: "/api/admin/hooks/specs",
} as const;
