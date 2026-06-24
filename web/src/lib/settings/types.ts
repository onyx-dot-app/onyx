import type { Notification } from "@/lib/notifications/interfaces";

export enum ApplicationStatus {
  PAYMENT_REMINDER = "payment_reminder",
  GATED_ACCESS = "gated_access",
  ACTIVE = "active",
  SEAT_LIMIT_EXCEEDED = "seat_limit_exceeded",
}

export enum Tier {
  COMMUNITY = "community",
  BUSINESS = "business",
  ENTERPRISE = "enterprise",
}

export enum QueryHistoryType {
  DISABLED = "disabled",
  ANONYMIZED = "anonymized",
  NORMAL = "normal",
}

export interface Settings {
  anonymous_user_enabled: boolean;
  invite_only_enabled: boolean;
  anonymous_user_path?: string;
  maximum_chat_retention_days?: number | null;
  company_name?: string | null;
  company_description?: string | null;
  notifications: Notification[];
  needs_reindexing: boolean;
  gpu_enabled: boolean;
  application_status: ApplicationStatus;
  auto_scroll: boolean;
  temperature_override_enabled: boolean;
  query_history_type: QueryHistoryType;

  // Visibility-only: hides the sidebar page; query-history APIs + recording stay on.
  hide_query_history_from_admin_panel?: boolean;

  deep_research_enabled?: boolean;
  multi_model_chat_enabled?: boolean;
  search_ui_enabled?: boolean;

  // Image processing settings
  image_extraction_and_analysis_enabled?: boolean;
  image_analysis_max_size_mb?: number | null;

  // User Knowledge settings
  user_knowledge_enabled?: boolean;
  user_file_max_upload_size_mb?: number | null;
  file_token_count_threshold_k?: number | null;

  // Connector settings
  show_extra_connectors?: boolean;

  // Default Assistant settings
  disable_default_assistant?: boolean;

  // Onyx Craft (Build Mode) feature flag
  onyx_craft_enabled?: boolean;

  // Dev/debug flag: when true, the Craft UI renders an "Opencode pod logs"
  // button that streams the user's sandbox pod logs in real time. Backed
  // by the ENABLE_OPENCODE_DEBUGGING env var on the server. Never set in
  // production — the underlying SSE endpoint also gates on the env var.
  opencode_debugging_enabled?: boolean;

  // Whether EE features are unlocked (user has a valid enterprise license).
  // Controls UI visibility of EE features like user groups, analytics, RBAC.
  ee_features_enabled?: boolean;
  tier?: Tier;

  // Seat usage - populated when seat limit is exceeded
  seat_count?: number | null;
  used_seats?: number | null;

  // OpenSearch migration
  opensearch_indexing_enabled?: boolean;

  // Vector DB availability flag - false when DISABLE_VECTOR_DB is set.
  // When false, connectors, RAG search, document sets, and related features
  // are unavailable.
  vector_db_enabled?: boolean;

  // True when hooks are available: single-tenant deployment with HOOK_ENABLED=true.
  hooks_enabled?: boolean;

  // Application version from the ONYX_VERSION env var on the server.
  version?: string | null;
  // Hard ceiling for user_file_max_upload_size_mb, derived from env var.
  max_allowed_upload_size_mb?: number;

  // Factory defaults for the restore button.
  default_pruning_freq?: number;
  default_user_file_max_upload_size_mb?: number;
  default_file_token_count_threshold_k?: number;

  // True when the backend runs inside a container (Docker/Podman).
  // Used to default local-service URLs to host.docker.internal.
  is_containerized?: boolean;

  // PostHog client key + host for the web app; null = analytics off.
  posthog_key?: string | null;
  posthog_host?: string | null;
}

export interface NavigationItem {
  link: string;
  icon?: string;
  svg_logo?: string;
  title: string;
}

export interface EnterpriseSettings {
  application_name: string | null;
  use_custom_logo: boolean;
  use_custom_logotype: boolean;
  logo_display_style: "logo_and_name" | "logo_only" | "name_only" | null;

  // custom navigation
  custom_nav_items: NavigationItem[];

  // custom Chat components
  custom_lower_disclaimer_content: string | null;
  custom_header_content: string | null;
  two_lines_for_chat_header: boolean | null;
  custom_popup_header: string | null;
  custom_popup_content: string | null;
  enable_consent_screen: boolean | null;
  consent_screen_prompt: string | null;
  show_first_visit_notice: boolean | null;
  custom_greeting_message: string | null;

  // Custom help link surfaced in the profile dropdown alongside "Help & FAQ".
  custom_help_link_url: string | null;
  custom_help_link_label: string | null;

  // Hide the "Powered by Onyx" tagline under the sidebar logo.
  hide_onyx_branding: boolean | null;
}

/**
 * Combined settings shape returned by the server-side `fetchSettingsSS`
 * helper in `lib/settings/svcSS.ts`. Used only for SSR — client
 * components access settings via the SWR hooks in `lib/settings/hooks.ts`.
 */
export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
  webVersion: string | null;
  webDomain: string | null;
  appName: string;
}

/**
 * Strip the derived/frontend-only fields from an `AppSettings` object,
 * returning only the plain `Settings` slice safe to send to the backend.
 */
export function toSettings({
  enterprise: _enterprise,
  appName: _appName,
  vectorDbEnabled: _vectorDbEnabled,
  isLoading: _isLoading,
  error: _error,
  ...core
}: AppSettings): Settings {
  return core;
}

/**
 * The fully-derived application settings object returned by `useSettings()`.
 *
 * Extends `Settings` with enterprise data and pre-computed derived fields so
 * callers never have to fetch enterprise settings separately or re-derive
 * values like `appName`.
 */
export interface AppSettings extends Settings {
  /** Raw enterprise settings — null when EE is disabled or not yet loaded. */
  enterprise: EnterpriseSettings | null;
  /** Resolved display name: enterprise.application_name || "Onyx". */
  appName: string;
  /**
   * URL of the logo image to render, or `null` to use the default Onyx SVG.
   * Includes a cache-buster that updates whenever enterprise settings are
   * revalidated, forcing the browser to re-fetch after an admin uploads a
   * new logo.
   */
  logoUrl: string | null;
  /** False when DISABLE_VECTOR_DB is set server-side. */
  vectorDbEnabled: boolean;
  isLoading: boolean;
  error: Error | undefined;
}
