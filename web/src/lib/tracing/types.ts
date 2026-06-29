export type TracingProviderType = "braintrust" | "langfuse";

export type TracingProviderSource = "db" | "env" | "none";

export interface TracingProviderView {
  provider_type: TracingProviderType;
  connected: boolean;
  source: TracingProviderSource;
  enabled: boolean;
  config: Record<string, string>;
  masked_api_key: string | null;
}

export interface TracingDisconnectTarget {
  providerType: TracingProviderType;
  label: string;
}
