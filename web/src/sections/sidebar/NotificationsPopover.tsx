"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { Route } from "next";
import { usePostHog } from "posthog-js/react";
import {
  Notification,
  NotificationType,
} from "@/app/admin/settings/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgSparkle, SvgRefreshCw, SvgX } from "@opal/icons";
import { IconProps } from "@opal/types";
import { Button } from "@opal/components";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import Separator from "@/refresh-components/Separator";

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
  const posthog = usePostHog();
  const {
    data: notifications,
    mutate,
    isLoading,
  } = useSWR<Notification[]>("/api/notifications", errorHandlingFetcher);

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
      posthog?.capture("release_notification_clicked", {
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
    <Section gap={0.5} padding={0.25}>
      <Section flexDirection="row" justifyContent="between" padding={0.5}>
        <Text headingH3>Notifications</Text>
        <Button icon={SvgX} prominence="tertiary" size="sm" onClick={onClose} />
      </Section>

      <Separator noPadding className="px-2" />

      <Section>
        {isLoading ? (
          <div className="h-48">
            <Section>
              <SimpleLoader />
            </Section>
          </div>
        ) : !notifications || notifications.length === 0 ? (
          <div className="h-48">
            <Section>
              <Text as="p" text03>
                No notifications
              </Text>
            </Section>
          </div>
        ) : (
          <div className="max-h-96 overflow-y-auto w-full">
            <Section alignItems="stretch" gap={0}>
              {notifications.map((notification) => (
                <LineItem
                  key={notification.id}
                  icon={getNotificationIcon(notification.notif_type)}
                  description={notification.description ?? undefined}
                  onClick={() => handleNotificationClick(notification)}
                  strikethrough={notification.dismissed}
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
                >
                  {notification.title}
                </LineItem>
              ))}
            </Section>
          </div>
        )}
      </Section>
    </Section>
  );
}
