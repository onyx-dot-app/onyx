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
  SvgCheckSquare,
  SvgSquare,
  SvgNotificationBubble,
} from "@opal/icons";
import type { IconProps } from "@opal/types";
import { Button, Divider, SelectCard, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
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

type NotificationState = "new" | "dismissed" | "older";

interface NotificationItemProps {
  notification: NotificationData;
  state: NotificationState;
  onClick: () => void;
  onDismiss: (id: number) => void;
}

function NotificationItem({
  notification,
  state,
  onClick,
  onDismiss,
}: NotificationItemProps) {
  const hoverGroup = `notif-${notification.id}`;

  return (
    <Hoverable.Root group={hoverGroup}>
      <SelectCard onClick={onClick} padding="sm" rounding="sm">
        <div className="flex flex-row gap-1 items-start">
          <div className="flex-1 min-w-0">
            <ContentAction
              icon={getNotificationIcon(notification.notif_type)}
              title={notification.title}
              description={notification.description ?? undefined}
              sizePreset="main-ui"
              variant="section"
              color={state === "new" ? "interactive" : "muted"}
              padding="fit"
              rightChildren={
                <Text font="secondary-body" color="text-02">
                  {formatRelativeDate(notification.first_shown)}
                </Text>
              }
            />
          </div>

          <div className="flex items-center justify-center w-6 shrink-0">
            {state === "new" ? (
              <div className="relative flex items-center justify-center w-6 h-6">
                {/* Dot: visible at rest, fades out on hover */}
                <div className="absolute inset-0 flex items-center justify-center transition-opacity opacity-100 [div[data-hover-group]:hover_&]:opacity-0">
                  <SvgNotificationBubble size={6} />
                </div>
                {/* Check: hidden at rest, fades in on hover */}
                <Hoverable.Item group={hoverGroup} variant="opacity-on-hover">
                  <Button
                    icon={SvgCheckSquare}
                    size="sm"
                    prominence="tertiary"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDismiss(notification.id);
                    }}
                    tooltip="Mark as read"
                  />
                </Hoverable.Item>
              </div>
            ) : (
              <Hoverable.Item group={hoverGroup} variant="opacity-on-hover">
                <Button icon={SvgSquare} size="sm" prominence="tertiary" />
              </Hoverable.Item>
            )}
          </div>
        </div>
      </SelectCard>
    </Hoverable.Root>
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
      if (sessionDismissedIds.has(notification.id)) return "dismissed";
      if (notification.dismissed) return "older";
      return "new";
    },
    [sessionDismissedIds]
  );

  const newNotifications = useMemo(
    () => notifications?.filter((n) => getState(n) === "new") ?? [],
    [notifications, getState]
  );
  const dismissedNotifications = useMemo(
    () => notifications?.filter((n) => getState(n) === "dismissed") ?? [],
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
    <div className="flex flex-col gap-1 p-1">
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
              <div className="flex flex-col">
                {newNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    state="new"
                    onClick={() => handleNotificationClick(notification)}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            </>
          )}

          {dismissedNotifications.length > 0 && (
            <>
              <Divider title="Dismissed" />
              <div className="flex flex-col">
                {dismissedNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    state="dismissed"
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
              <div className="flex flex-col">
                {olderNotifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    state="older"
                    onClick={() => handleNotificationClick(notification)}
                    onDismiss={handleDismiss}
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
