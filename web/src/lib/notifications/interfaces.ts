export enum NotificationType {
  // SvgAlertCircle
  PERSONA_SHARED = "persona_shared",
  REINDEX = "reindex",
  ASSISTANT_FILES_READY = "assistant_files_ready",
  CONNECTOR_REPEATED_ERRORS = "connector_repeated_errors",
  SCHEDULED_TASK_PRE_APPROVED_ACTION = "scheduled_task_pre_approved_action",
  APPROVAL_REQUESTED = "approval_requested",

  // SvgAlertTriangle
  TRIAL_ENDS_TWO_DAYS = "two_day_trial_ending",
  LICENSE_EXPIRY_WARNING = "license_expiry_warning",
  SCHEDULED_TASK_FAILED = "scheduled_task_failed",
  SCHEDULED_TASK_AWAITING_APPROVAL = "scheduled_task_awaiting_approval",

  // SvgBullhorn
  RELEASE_NOTES = "release_notes",
  FEATURE_ANNOUNCEMENT = "feature_announcement",
}

export interface Notification {
  id: number;
  notif_type: NotificationType;
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
  } | null;
}

export interface NotificationsResponse {
  notifications: Notification[];
  total_items: number;
  undismissed_count: number;
  page_num: number;
  page_size: number;
  has_more: boolean;
}

export interface NotificationSummary {
  total_items: number;
  undismissed_count: number;
}
