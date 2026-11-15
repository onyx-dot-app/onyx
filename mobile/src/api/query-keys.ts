export const QUERY_KEYS = {
  /*
   * Keyed by serverUrl so switching instances never serves the prior backend's
   * cached identity/config.
   */
  me: (serverUrl: string | null) => ["me", serverUrl] as const,
  authType: (serverUrl: string | null) => ["auth-type", serverUrl] as const,
  chatSessions: (serverUrl: string | null) =>
    ["chat-sessions", serverUrl] as const,
  chatSession: (serverUrl: string | null, sessionId: string) =>
    ["chat-session", serverUrl, sessionId] as const,
  agents: (serverUrl: string | null) => ["agents", serverUrl] as const,
  workspaceSettings: (serverUrl: string | null) =>
    ["workspace-settings", serverUrl] as const,
  userProjects: (serverUrl: string | null) => ["projects", serverUrl] as const,
  userProject: (serverUrl: string | null, projectId: number | null) =>
    ["project", serverUrl, projectId] as const,
  userRecentFiles: (serverUrl: string | null) =>
    ["recent-files", serverUrl] as const,
  agentPreferences: (serverUrl: string | null) =>
    ["agent-preferences", serverUrl] as const,
  connectorSources: (serverUrl: string | null) =>
    ["connector-sources", serverUrl] as const,
  federatedSources: (serverUrl: string | null) =>
    ["federated-sources", serverUrl] as const,
  availableTools: (serverUrl: string | null) =>
    ["available-tools", serverUrl] as const,
  llmProviders: (serverUrl: string | null, agentId: number | null) =>
    ["llm-providers", serverUrl, agentId] as const,
};
