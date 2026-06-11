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

export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
  isMobile?: boolean;
  webVersion: string | null;
  webDomain: string | null;

  /**
   * NOTE (@raunakab):
   * Whether search mode is actually available to users.
   *
   * Prefer this over reading `settings.search_ui_enabled` directly.
   * `search_ui_enabled` only reflects the admin's *preference* — it does not
   * account for prerequisites like connectors being configured. This derived
   * flag combines the admin setting with runtime checks (e.g. connectors
   * exist) so consumers get a single, accurate boolean.
   */
  isSearchModeAvailable: boolean;
  settingsLoading: boolean;
}
