export type TracingProviderType = "braintrust" | "langfuse";

export type TracingProviderSource = "db" | "env" | "none";

export interface TracingProviderView {
  provider_type: TracingProviderType;
  connected: boolean;
  source: TracingProviderSource;
  enabled: boolean;
  config: Record<string, string>;
  masked_api_key: string | null;
  /** Env vars configure it; a DB row overrides them. */
  env_configured: boolean;
}

export interface TracingDisconnectTarget {
  providerType: TracingProviderType;
  label: string;
  config: Record<string, string>;
}
