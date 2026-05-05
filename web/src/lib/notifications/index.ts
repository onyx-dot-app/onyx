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
      return SvgAlertCircle;

    case NotificationType.TRIAL_ENDS_TWO_DAYS:
    case NotificationType.LICENSE_EXPIRY_WARNING:
      return SvgAlertTriangle;

    case NotificationType.RELEASE_NOTES:
    case NotificationType.FEATURE_ANNOUNCEMENT:
      return SvgBullhorn;

    default:
      return SvgAlertCircle;
  }
}
