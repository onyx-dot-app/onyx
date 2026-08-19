import type { Route } from "next";
import type { useRouter } from "next/navigation";
import { SvgAlertCircle, SvgAlertTriangle, SvgBullhorn } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { NotificationType } from "@/lib/notifications/interfaces";

export function isExternalLink(link: string): boolean {
  return link.startsWith("http://") || link.startsWith("https://");
}

// Internal links must be absolute paths. Rejects other schemes (mailto:,
// tel:) and protocol-relative //host values, which router.push would
// otherwise navigate to unvalidated.
function isInternalPath(link: string): boolean {
  return link.startsWith("/") && !link.startsWith("//");
}

export function openNotificationLink(
  link: string,
  router: ReturnType<typeof useRouter>
): void {
  if (isExternalLink(link)) {
    window.open(link, "_blank", "noopener,noreferrer");
    return;
  }
  if (!isInternalPath(link)) {
    console.error("Ignoring notification link with unsupported format:", link);
    return;
  }
  router.push(link as Route);
}

export function getNotificationIcon(
  notifType: string
): React.FunctionComponent<IconProps> {
  switch (notifType) {
    case NotificationType.PERSONA_SHARED:
    case NotificationType.REINDEX:
    case NotificationType.ASSISTANT_FILES_READY:
    case NotificationType.CONNECTOR_REPEATED_ERRORS:
    case NotificationType.CONNECTOR_INVALID:
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
    case NotificationType.SYSTEM_ANNOUNCEMENT:
      return SvgBullhorn;

    default:
      return SvgAlertCircle;
  }
}
