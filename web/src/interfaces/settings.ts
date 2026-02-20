export enum ApplicationStatus {
  PAYMENT_REMINDER = "payment_reminder",
  GATED_ACCESS = "gated_access",
  ACTIVE = "active",
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

  deep_research_enabled?: boolean;
  search_ui_enabled?: boolean;

  // Image processing settings
  image_extraction_and_analysis_enabled?: boolean;
  search_time_image_analysis_enabled?: boolean;
  image_analysis_max_size_mb?: number | null;

  // User Knowledge settings
  user_knowledge_enabled?: boolean;

  // Connector settings
  show_extra_connectors?: boolean;

  // Default Assistant settings
  disable_default_assistant?: boolean;

  // Onyx Craft (Build Mode) feature flag
  onyx_craft_enabled?: boolean;

  // Enterprise features flag - controlled by license enforcement at runtime
  // True when user has a valid license, False for community edition
  ee_features_enabled?: boolean;

  // OpenSearch migration
  opensearch_indexing_enabled?: boolean;

  // Vector DB availability flag - false when DISABLE_VECTOR_DB is set.
  // When false, connectors, RAG search, document sets, and related features
  // are unavailable.
  vector_db_enabled?: boolean;
}

export enum NotificationType {
  PERSONA_SHARED = "persona_shared",
  REINDEX = "reindex",
  TRIAL_ENDS_TWO_DAYS = "two_day_trial_ending",
  ASSISTANT_FILES_READY = "assistant_files_ready",
  RELEASE_NOTES = "release_notes",
  FEATURE_ANNOUNCEMENT = "feature_announcement",
}

export interface Notification {
  id: number;
  notif_type: string;
  title: string;
  description: string | null;
  dismissed: boolean;
  first_shown: string;
  last_shown: string;
  additional_data?: {
    persona_id?: number;
    link?: string;
    version?: string; // For release notes notifications
    [key: string]: any;
  };
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
}
