import type { useTranslations } from "next-intl";
import type { IconFunctionComponent, RichStr } from "@opal/types";

// Registry text (content subtitles, config fields) lives in "admin.webSearch".
export type WebSearchTranslate = ReturnType<
  typeof useTranslations<"admin.webSearch">
>;
export type WebSearchMessageKey = Parameters<WebSearchTranslate>[0];

// ── Provider type literals ────────────────────────────────────────────────────

export type WebSearchProviderType =
  | "google_pse"
  | "serper"
  | "exa"
  | "searxng"
  | "brave"
  | "ollama"
  | "tavily";

export type WebContentProviderType =
  | "firecrawl"
  | "onyx_web_crawler"
  | "exa"
  | "tavily"
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
  // Brand or product name, not translated.
  subtitle: string;
  logo?: IconFunctionComponent;
  apiKeyUrl?: string;
}

export interface ContentProviderDetail {
  label: string;
  subtitleKey: WebSearchMessageKey;
  logo?: IconFunctionComponent;
}
