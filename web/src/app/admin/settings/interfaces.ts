export interface Settings {
  chat_page_enabled: boolean;
  search_page_enabled: boolean;
  default_page: "search" | "chat";
  maximum_chat_retention_days: number | null;
}

export interface EnterpriseSettings {
  application_name: string | null;
  use_custom_logo: boolean;

  // custom Chat components
  custom_header_content: string | null;
  custom_popup_header: string | null;
  custom_popup_content: string | null;
}

export interface CombinedSettings {
  settings: Settings;
  enterpriseSettings: EnterpriseSettings | null;
  customAnalyticsScript: string | null;
}
