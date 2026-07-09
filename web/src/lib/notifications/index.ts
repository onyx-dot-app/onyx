import { SvgAlertCircle, SvgAlertTriangle, SvgBullhorn } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { NotificationType } from "@/lib/notifications/interfaces";

export function getNotificationIcon(
  notifType: string
): React.FunctionComponent<IconProps> {
  switch (notifType) {
    case NotificationType.PERSONA_SHARED:
    case NotificationType.REINDEX:
    case NotificationType.ASSISTANT_FILES_READY:
    case NotificationType.CONNECTOR_REPEATED_ERRORS:
    case NotificationType.SCHEDULED_TASK_PRE_APPROVED_ACTION:
    case NotificationType.APPROVAL_REQUESTED:
      return SvgAlertCircle;

    case NotificationType.TRIAL_ENDS_TWO_DAYS:
    case NotificationType.LICENSE_EXPIRY_WARNING:
    case NotificationType.SCHEDULED_TASK_FAILED:
    case NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL:
      return SvgAlertTriangle;

    case NotificationType.RELEASE_NOTES:
    case NotificationType.FEATURE_ANNOUNCEMENT:
      return SvgBullhorn;

    default:
      return SvgAlertCircle;
  }
}
