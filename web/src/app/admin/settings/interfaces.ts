export enum GatingType {
  FULL = "full",
  PARTIAL = "partial",
  NONE = "none",
}

export interface Settings {
  chat_page_enabled: boolean;
  search_page_enabled: boolean;
  default_page: "search" | "chat";
  maximum_chat_retention_days: number | null;
  notifications: Notification[];
  needs_reindexing: boolean;
  gpu_enabled: boolean;
  product_gating: GatingType;
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
}
