import type { WebSearchProviderType } from "./searchProviderUtils";
import type { WebContentProviderType } from "./contentProviderUtils";

export interface WebSearchProviderView {
  id: number;
  name: string;
  provider_type: WebSearchProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  has_api_key: boolean;
}

export interface WebContentProviderView {
  id: number;
  name: string;
  provider_type: WebContentProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  has_api_key: boolean;
}

export interface DisconnectTargetState {
  id: number;
  label: string;
  category: "search" | "content";
  providerType: string;
}
