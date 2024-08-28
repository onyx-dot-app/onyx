export interface Settings {
  chat_page_enabled: boolean;
  search_page_enabled: boolean;
  default_page: "search" | "chat";
  maximum_chat_retention_days: number | null;
  notifications: Notification[];
  needs_reindexing: boolean;
}

export interface Notification {
  id: number;
  notif_type: string;
  dismissed: boolean;
  last_shown: string;
  first_shown: string;
}

export interface EnterpriseSettings {
  application_name: string | null;
  use_custom_logo: boolean;
  use_custom_logotype: boolean;

  // custom Chat components
  custom_lower_disclaimer_content: string | null;
  custom_header_content: string | null;
  custom_popup_header: string | null;
  custom_popup_content: string | null;
}

export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
  isMobile?: boolean;
  webVersion: string | null;
}
