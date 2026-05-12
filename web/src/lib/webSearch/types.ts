import type { IconFunctionComponent, RichStr } from "@opal/types";

// ── Provider type literals ────────────────────────────────────────────────────

export type WebSearchProviderType =
  | "google_pse"
  | "serper"
  | "exa"
  | "searxng"
  | "brave";

export type WebContentProviderType =
  | "firecrawl"
  | "onyx_web_crawler"
  | "exa"
  | (string & {});

/** Which web-search provider category we are configuring. */
export type WebProviderCategory = "search" | "content";

// ── Provider config shapes ────────────────────────────────────────────────────

export type SearchProviderConfig = Record<string, string> | null | undefined;

export type SearchProviderLike =
  | { masked_api_key: string | null; config: SearchProviderConfig }
  | null
  | undefined;

export type ContentProviderConfig = Record<string, string> | null | undefined;

export type ContentProviderLike =
  | { masked_api_key: string | null; config: ContentProviderConfig }
  | null
  | undefined;

// ── API view shapes ───────────────────────────────────────────────────────────

export interface WebSearchProviderView {
  id: number;
  name: string;
  provider_type: WebSearchProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  masked_api_key: string | null;
}

export interface WebContentProviderView {
  id: number;
  name: string;
  provider_type: WebContentProviderType;
  is_active: boolean;
  config: Record<string, string> | null;
  masked_api_key: string | null;
}

// ── UI state ──────────────────────────────────────────────────────────────────

export interface DisconnectTargetState {
  id: number;
  label: string;
  category: "search" | "content";
  providerType: string;
}

// ── connectProviderFlow wire types ────────────────────────────────────────────

export type ProviderTestPayload = {
  provider_type: string;
  api_key: string | null;
  use_stored_key: boolean;
  config: Record<string, string>;
};

export type ProviderUpsertPayload = {
  id: number | null;
  name: string;
  provider_type: string;
  api_key: string | null;
  api_key_changed: boolean;
  config: Record<string, string>;
  activate: boolean;
};

// ── Config field spec ─────────────────────────────────────────────────────────

export interface ConfigFieldSpec {
  title: string;
  placeholder: string;
  subDescription?: string | RichStr;
  defaultValue?: string;
}

// ── Provider detail registry types ───────────────────────────────────────────

export interface SearchProviderDetail {
  label: string;
  subtitle: string;
  helper: string;
  logo?: IconFunctionComponent;
  apiKeyUrl?: string;
}

export interface ContentProviderDetail {
  label: string;
  subtitle: string;
  description: string;
  logo?: IconFunctionComponent;
}
