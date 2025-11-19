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

  // Image processing settings
  image_extraction_and_analysis_enabled?: boolean;
  search_time_image_analysis_enabled?: boolean;
  image_analysis_max_size_mb?: number | null;

  // User Knowledge settings
  user_knowledge_enabled?: boolean;

  // Connector settings
  show_extra_connectors?: boolean;
}

export enum NotificationType {
  PERSONA_SHARED = "persona_shared",
  REINDEX_NEEDED = "reindex_needed",
  TRIAL_ENDS_TWO_DAYS = "two_day_trial_ending",
}

export interface Notification {
  id: number;
  notif_type: string;
  time_created: string;
  dismissed: boolean;
  additional_data?: {
    persona_id?: number;
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

  // custom navigation
  custom_nav_items: NavigationItem[];

  // custom Chat components
  custom_lower_disclaimer_content: string | null;
  custom_header_content: string | null;
  two_lines_for_chat_header: boolean | null;
  custom_popup_header: string | null;
  custom_popup_content: string | null;
  enable_consent_screen: boolean | null;
}

export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
  isMobile?: boolean;
  webVersion: string | null;
  webDomain: string | null;
}
