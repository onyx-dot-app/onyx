export enum NotificationType {
  // SvgAlertCircle
  PERSONA_SHARED = "persona_shared",
  REINDEX = "reindex",
  ASSISTANT_FILES_READY = "assistant_files_ready",

  // SvgAlertTriangle
  TRIAL_ENDS_TWO_DAYS = "two_day_trial_ending",

  // SvgBullhorn
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
