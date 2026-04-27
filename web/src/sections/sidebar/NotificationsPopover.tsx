"use client";

import { useRouter } from "next/navigation";
import { Route } from "next";
import { track, AnalyticsEvent } from "@/lib/analytics";
import {
  Notification as NotificationData,
  NotificationType,
} from "@/interfaces/settings";
import useNotifications from "@/hooks/useNotifications";
import {
  SvgSparkle,
  SvgRefreshCw,
  SvgX,
  SvgBullhorn,
  SvgCheckAll,
} from "@opal/icons";
import type { IconProps } from "@opal/types";
import { Button, Divider, LineItemButton, Text } from "@opal/components";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import { ContentAction, IllustrationContent } from "@opal/layouts";
import { SvgEmpty } from "@opal/illustrations";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getNotificationIcon(
  notifType: string
): React.FunctionComponent<IconProps> {
  switch (notifType) {
    case NotificationType.REINDEX:
      return SvgRefreshCw;
    case NotificationType.RELEASE_NOTES:
      return SvgBullhorn;
    default:
      return SvgSparkle;
  }
}

function formatRelativeDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// NotificationItem
// ---------------------------------------------------------------------------

interface NotificationItemProps {
  notification: NotificationData;
  onClick: () => void;
  onDismiss: (id: number, e?: React.MouseEvent) => void;
}

function NotificationItem({
  notification,
  onClick,
  onDismiss,
}: NotificationItemProps) {
  const isNew = !notification.dismissed;

  return (
    <LineItemButton
      icon={getNotificationIcon(notification.notif_type)}
      title={notification.title}
      description={notification.description ?? undefined}
      selectVariant="select-heavy"
      sizePreset="main-ui"
      rounding="sm"
      state={isNew ? "selected" : "empty"}
      color={isNew ? "interactive" : "muted"}
      onClick={onClick}
      rightChildren={
        <div className="flex flex-col items-end gap-1">
          <Text font="secondary-body" color="text-02">
            {formatRelativeDate(notification.first_shown)}
          </Text>
          {isNew && (
            <Button
              prominence="tertiary"
              size="sm"
              icon={SvgCheckAll}
              onClick={(e) => onDismiss(notification.id, e)}
              tooltip="Mark as read"
            />
          )}
        </div>
      }
    />
  );
}

// ---------------------------------------------------------------------------
// NotificationsPopover
// ---------------------------------------------------------------------------

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

  const handleNotificationClick = (notification: NotificationData) => {
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

    if (notification.notif_type === NotificationType.RELEASE_NOTES) {
      track(AnalyticsEvent.RELEASE_NOTIFICATION_CLICKED, {
        version: notification.additional_data?.version,
      });
    }

    if (link.startsWith("http://") || link.startsWith("https://")) {
      if (!notification.dismissed) {
        handleDismiss(notification.id);
      }
      window.open(link, "_blank", "noopener,noreferrer");
      return;
    }

    onNavigate();
    router.push(link as Route);
  };

  const handleDismiss = async (
    notificationId: number,
    e?: React.MouseEvent
  ) => {
    e?.stopPropagation();
    try {
      const response = await fetch(
        `/api/notifications/${notificationId}/dismiss`,
        { method: "POST" }
      );
      if (response.ok) {
        mutate();
      }
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  };

  const newNotifications = notifications?.filter((n) => !n.dismissed) ?? [];
  const olderNotifications = notifications?.filter((n) => n.dismissed) ?? [];

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
        <div className="max-h-[var(--notifications-popover)] overflow-y-auto flex flex-col">
          {newNotifications.length > 0 && (
            <>
              <Divider title="New" />
              <div className="flex flex-col gap-1 px-1">
                {newNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onClick={() => handleNotificationClick(notification)}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            </>
          )}

          {olderNotifications.length > 0 && (
            <>
              <Divider title="Older" />
              <div className="flex flex-col gap-1 px-1">
                {olderNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onClick={() => handleNotificationClick(notification)}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </Section>
  );
}
