"use client";

import { useCallback, useMemo, useState } from "react";
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
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------------
// NotificationItem
// ---------------------------------------------------------------------------

type NotificationState = "new" | "older";

interface NotificationItemProps {
  notification: NotificationData;
  state: NotificationState;
  onClick: () => void;
}

function NotificationItem({
  notification,
  state,
  onClick,
}: NotificationItemProps) {
  return (
    <LineItemButton
      icon={getNotificationIcon(notification.notif_type)}
      title={notification.title}
      description={notification.description ?? undefined}
      sizePreset="main-ui"
      rounding="sm"
      color={state === "new" ? undefined : "muted"}
      onClick={onClick}
      rightChildren={
        <Text font="secondary-body" color="text-02">
          {formatRelativeDate(notification.first_shown)}
        </Text>
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

  // Track IDs dismissed during this session (before popover closes)
  const [sessionDismissedIds, setSessionDismissedIds] = useState<Set<number>>(
    new Set()
  );

  const handleNotificationClick = useCallback(
    (notification: NotificationData) => {
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
    },
    [onNavigate, onShowBuildIntro, router]
  );

  const handleDismiss = useCallback(
    async (notificationId: number) => {
      try {
        const response = await fetch(
          `/api/notifications/${notificationId}/dismiss`,
          { method: "POST" }
        );
        if (response.ok) {
          setSessionDismissedIds((prev) => new Set([...prev, notificationId]));
          mutate();
        }
      } catch (error) {
        console.error("Error dismissing notification:", error);
      }
    },
    [mutate]
  );

  const getState = useCallback(
    (notification: NotificationData): NotificationState => {
      if (sessionDismissedIds.has(notification.id) || notification.dismissed)
        return "older";
      return "new";
    },
    [sessionDismissedIds]
  );

  const newNotifications = useMemo(
    () => notifications?.filter((n) => getState(n) === "new") ?? [],
    [notifications, getState]
  );
  const olderNotifications = useMemo(
    () => notifications?.filter((n) => getState(n) === "older") ?? [],
    [notifications, getState]
  );

  const handleDismissAll = useCallback(async () => {
    for (const n of newNotifications) {
      await handleDismiss(n.id);
    }
  }, [newNotifications, handleDismiss]);

  return (
    <div className="flex flex-col gap-1">
      <ContentAction
        title="Notifications"
        sizePreset="main-content"
        tag={{
          title: `${undismissedCount} unread`,
          color: "blue",
        }}
        rightChildren={
          <div className="flex flex-row items-center gap-1">
            {newNotifications.length > 0 && (
              <Button
                icon={SvgCheckAll}
                onClick={handleDismissAll}
                size="sm"
                prominence="tertiary"
                tooltip="Mark all as read"
              />
            )}
            <Button
              icon={SvgX}
              onClick={onClose}
              size="sm"
              prominence="tertiary"
            />
          </div>
        }
        padding="fit"
      />

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
        <div className="max-h-[var(--notifications-popover)] overflow-y-auto flex flex-col gap-1">
          {newNotifications.length > 0 && (
            <>
              <Divider title="New" />
              <div className="flex flex-col gap-1">
                {newNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    state="new"
                    onClick={() => handleNotificationClick(notification)}
                  />
                ))}
              </div>
            </>
          )}

          {olderNotifications.length > 0 && (
            <>
              <Divider title="Older" />
              <div className="flex flex-col gap-1">
                {olderNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    state="older"
                    onClick={() => handleNotificationClick(notification)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
