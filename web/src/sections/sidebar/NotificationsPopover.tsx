"use client";

import { useRouter } from "next/navigation";
import { Route } from "next";
import { track, AnalyticsEvent } from "@/lib/analytics";
import { Notification, NotificationType } from "@/interfaces/settings";
import useNotifications from "@/hooks/useNotifications";
import {
  SvgSparkle,
  SvgRefreshCw,
  SvgX,
  SvgNotificationBubble,
} from "@opal/icons";
import { IconProps } from "@opal/types";
import { Button, Divider, LineItemButton } from "@opal/components";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import { ContentAction, IllustrationContent } from "@opal/layouts";
import { SvgEmpty } from "@opal/illustrations";
import { markdown } from "@opal/utils";

function getNotificationIcon(
  notifType: string
): React.FunctionComponent<IconProps> {
  switch (notifType) {
    case NotificationType.REINDEX:
      return SvgRefreshCw;
    default:
      return SvgSparkle;
  }
}

interface NotificationsPopoverProps {
  onClose: () => void;
  onNavigate: () => void;
  onShowBuildIntro?: () => void;
}

export default function NotificationsPopover({
  onClose,
  onNavigate,
  onShowBuildIntro,
}: NotificationsPopoverProps) {
  const router = useRouter();
  const {
    notifications,
    undismissedCount,
    isLoading,
    refresh: mutate,
  } = useNotifications();

  const handleNotificationClick = (notification: Notification) => {
    // Handle build_mode feature announcement specially - show intro animation
    if (
      notification.notif_type === NotificationType.FEATURE_ANNOUNCEMENT &&
      notification.additional_data?.feature === "build_mode" &&
      onShowBuildIntro
    ) {
      onNavigate();
      onShowBuildIntro();
      return;
    }

    const link = notification.additional_data?.link;
    if (!link) return;

    // Track release notes clicks
    if (notification.notif_type === NotificationType.RELEASE_NOTES) {
      track(AnalyticsEvent.RELEASE_NOTIFICATION_CLICKED, {
        version: notification.additional_data?.version,
      });
    }

    // External links open in new tab
    if (link.startsWith("http://") || link.startsWith("https://")) {
      if (!notification.dismissed) {
        handleDismiss(notification.id);
      }
      window.open(link, "_blank", "noopener,noreferrer");
      return;
    }

    // Relative links navigate internally
    onNavigate();
    router.push(link as Route);
  };

  const handleDismiss = async (
    notificationId: number,
    e?: React.MouseEvent
  ) => {
    e?.stopPropagation(); // Prevent triggering the LineItem onClick
    try {
      const response = await fetch(
        `/api/notifications/${notificationId}/dismiss`,
        {
          method: "POST",
        }
      );
      if (response.ok) {
        mutate(); // Refresh the notifications list
      }
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  };

  return (
    <Section gap={0}>
      <div className="w-full p-2">
        <ContentAction
          title="Notifications"
          sizePreset="main-content"
          tag={{
            title: `${undismissedCount} unread`,
            color: "blue",
          }}
          rightChildren={
            <Button
              icon={SvgX}
              onClick={onClose}
              size="sm"
              prominence="tertiary"
            />
          }
          padding="fit"
        />
      </div>

      <Divider paddingPerpendicular="fit" />

      {isLoading ? (
        <div className="h-[var(--notifications-popover)]">
          <Section>
            <SimpleLoader />
          </Section>
        </div>
      ) : !notifications || notifications.length === 0 ? (
        <div className="h-[var(--notifications-popover)]">
          <Section>
            <IllustrationContent
              title="No notifications"
              illustration={SvgEmpty}
            />
          </Section>
        </div>
      ) : (
        <div className="max-h-[var(--notifications-popover)] overflow-y-auto pt-1 px-0 flex flex-col gap-1">
          {/* TODO(@raunakab): make dismissed notifications have greyed out text */}
          {notifications.map((notification) => (
            <LineItemButton
              key={notification.id}
              icon={getNotificationIcon(notification.notif_type)}
              title={markdown(
                notification.dismissed
                  ? `~~${notification.title}~~`
                  : notification.title
              )}
              selectVariant="select-heavy"
              sizePreset="main-ui"
              rounding="sm"
              state={notification.dismissed ? undefined : "selected"}
              description={notification.description ?? undefined}
              onClick={() => handleNotificationClick(notification)}
              rightChildren={
                !notification.dismissed ? (
                  <Button
                    prominence="tertiary"
                    size="sm"
                    icon={SvgX}
                    onClick={(e) => handleDismiss(notification.id, e)}
                    tooltip="Dismiss"
                  />
                ) : undefined
              }
            />
          ))}
        </div>
      )}
    </Section>
  );
}
