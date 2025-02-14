export enum ApplicationStatus {
  PAYMENT_REMINDER = "payment_reminder",
  GATED_ACCESS = "gated_access",
  ACTIVE = "active",
}

export interface Settings {
  anonymous_user_enabled: boolean;
  maximum_chat_retention_days: number | null;
  notifications: Notification[];
  needs_reindexing: boolean;
  gpu_enabled: boolean;
  pro_search_disabled: boolean | null;
  application_status: ApplicationStatus;
  auto_scroll: boolean;
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
  auto_scroll: boolean;
}

export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
  isMobile?: boolean;
  webVersion: string | null;
  webDomain: string | null;
}
