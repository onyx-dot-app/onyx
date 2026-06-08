"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Route } from "next";
import { track, AnalyticsEvent } from "@/lib/analytics";
import type { Notification as NotificationData } from "@/lib/notifications/interfaces";
import { NotificationType } from "@/lib/notifications/interfaces";
import { getNotificationIcon } from "@/lib/notifications";
import {
  dismissAllNotifications,
  dismissNotification,
} from "@/lib/notifications/api";
import { timeAgo } from "@opal/time";
import useNotifications from "@/hooks/useNotifications";
import {
  SvgCheckAll,
  SvgNotificationBubble,
  SvgCheckSquare,
  SvgChevronLeft,
  SvgSimpleLoader,
} from "@opal/icons";
import { Button, Divider, LineItemButton, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { IllustrationContent } from "@opal/layouts";
import { SvgEmpty } from "@opal/illustrations";
import { Hoverable } from "@opal/core";
import { noProp } from "@/lib/utils";

// ---------------------------------------------------------------------------
// NotificationItem
// ---------------------------------------------------------------------------

type NotificationState = "new" | "older";

interface NotificationItemProps {
  notification: NotificationData;
  state: NotificationState;
  onClick: () => void;
  dismiss: () => void;
}

function NotificationItem({
  notification,
  state,
  onClick,
  dismiss,
}: NotificationItemProps) {
  return (
    <Hoverable.Root group="notifications-popover/NotificationItem">
      <LineItemButton
        icon={getNotificationIcon(notification.notif_type)}
        title={notification.title}
        description={notification.description ?? undefined}
        sizePreset="main-ui"
        rounding="sm"
        color={state === "new" ? undefined : "muted"}
        onClick={onClick}
        rightChildren={
          <Section justifyContent="start">
            <Section height="fit" gap={0.5} flexDirection="row">
              <Text font="secondary-body" color="text-02">
                {timeAgo(notification.first_shown) ?? ""}
              </Text>
              {state === "new" && (
                <div className="w-4 flex flex-col items-center justify-center">
                  <Hoverable.Item
                    group="notifications-popover/NotificationItem"
                    variant="replace-on-hover"
                    resting={
                      <div className="w-full h-full p-1.5">
                        <div className="p-px">
                          <SvgNotificationBubble size={6} />
                        </div>
                      </div>
                    }
                  >
                    <Button
                      icon={SvgCheckSquare}
                      size="xs"
                      prominence="tertiary"
                      onClick={noProp(dismiss)}
                      tooltip="Mark as Read"
                    />
                  </Hoverable.Item>
                </div>
              )}
            </Section>
          </Section>
        }
      />
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
    refresh,
    hasMore,
    isLoadingMore,
    loadMore,
  } = useNotifications();
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef(loadMore);
  const lastLoadScrollTopRef = useRef<number | null>(null);
  loadMoreRef.current = loadMore;

  const [sessionDismissedVersionById, setSessionDismissedVersionById] =
    useState<Map<number, string>>(new Map());
  const dismissInFlightIdsRef = useRef<Set<number>>(new Set());

  const handleDismiss = useCallback(
    async (notification: NotificationData) => {
      const notificationId = notification.id;
      const expectedVersion = notification.version;
      if (dismissInFlightIdsRef.current.has(notificationId)) {
        return;
      }

      dismissInFlightIdsRef.current.add(notificationId);
      setSessionDismissedVersionById((prev) => {
        const next = new Map(prev);
        next.set(notificationId, expectedVersion);
        return next;
      });

      try {
        await dismissNotification(notificationId, expectedVersion);
        void refresh();
      } catch (error) {
        setSessionDismissedVersionById((prev) => {
          if (prev.get(notificationId) !== expectedVersion) {
            return prev;
          }
          const next = new Map(prev);
          next.delete(notificationId);
          return next;
        });
        console.error("Error dismissing notification:", error);
      } finally {
        dismissInFlightIdsRef.current.delete(notificationId);
      }
    },
    [refresh]
  );

  const getState = useCallback(
    (notification: NotificationData): NotificationState => {
      const dismissedVersion = sessionDismissedVersionById.get(notification.id);
      if (dismissedVersion === notification.version || notification.dismissed) {
        return "older";
      }
      return "new";
    },
    [sessionDismissedVersionById]
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
        if (getState(notification) === "new") {
          void handleDismiss(notification);
        }
        window.open(link, "_blank", "noopener,noreferrer");
        return;
      }

      if (getState(notification) === "new") {
        void handleDismiss(notification);
      }
      onNavigate();
      router.push(link as Route);
    },
    [getState, handleDismiss, onNavigate, onShowBuildIntro, router]
  );

  const newNotifications = useMemo(
    () => notifications.filter((n) => getState(n) === "new"),
    [notifications, getState]
  );
  const olderNotifications = useMemo(
    () => notifications.filter((n) => getState(n) === "older"),
    [notifications, getState]
  );

  const handleDismissAll = useCallback(async () => {
    try {
      await dismissAllNotifications();
      setSessionDismissedVersionById((prev) => {
        const next = new Map(prev);
        newNotifications.forEach((notification) => {
          next.set(notification.id, notification.version);
        });
        return next;
      });
      void refresh();
    } catch (error) {
      console.error("Error dismissing notifications:", error);
    }
  }, [refresh, newNotifications]);

  useEffect(() => {
    if (!hasMore || isLoadingMore) return;

    const scrollContainer = scrollContainerRef.current;
    const sentinel = sentinelRef.current;
    if (!scrollContainer || !sentinel) return;
    lastLoadScrollTopRef.current ??= Math.round(scrollContainer.scrollTop);

    let didRequestLoad = false;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !didRequestLoad) {
          const currentScrollTop = Math.round(scrollContainer.scrollTop);
          const isScrollable =
            scrollContainer.scrollHeight > scrollContainer.clientHeight + 1;
          if (
            isScrollable &&
            lastLoadScrollTopRef.current === currentScrollTop
          ) {
            return;
          }

          lastLoadScrollTopRef.current = currentScrollTop;
          didRequestLoad = true;
          observer.disconnect();
          loadMoreRef.current();
        }
      },
      {
        root: scrollContainer,
        rootMargin: "64px 0px",
        threshold: 0,
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoadingMore]);

  return (
    <Section gap={0} justifyContent="start" alignItems="stretch">
      <Section flexDirection="row" padding={0.325}>
        <Section flexDirection="row" gap={0.25} justifyContent="start">
          <Button
            icon={SvgChevronLeft}
            size="sm"
            prominence="tertiary"
            onClick={onClose}
          />
          <Text color="text-02">Notifications</Text>
        </Section>

        <Section flexDirection="row" gap={0.25} justifyContent="end">
          {undismissedCount !== 0 && (
            <span className="text-action-link-05 font-secondary-body">
              {`${undismissedCount} unread`}
            </span>
          )}
          <Button
            icon={SvgCheckAll}
            size="sm"
            prominence="tertiary"
            onClick={handleDismissAll}
            tooltip="Mark All as Read"
            disabled={undismissedCount === 0}
          />
        </Section>
      </Section>

      {isLoading ? (
        <div className="h-(--notifications-popover)">
          <Section>
            <SvgSimpleLoader />
          </Section>
        </div>
      ) : !notifications || notifications.length === 0 ? (
        <div className="h-(--notifications-popover)">
          <Section>
            <IllustrationContent
              title="No notifications"
              illustration={SvgEmpty}
            />
          </Section>
        </div>
      ) : (
        <div
          ref={scrollContainerRef}
          className="h-(--notifications-popover) w-full min-w-0 overflow-y-auto [overflow-anchor:none] [scrollbar-gutter:stable] flex flex-col gap-1"
        >
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
                    dismiss={() => void handleDismiss(notification)}
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
                    dismiss={() => void handleDismiss(notification)}
                  />
                ))}
              </div>
            </>
          )}

          {hasMore && (
            <div
              ref={sentinelRef}
              className="h-8 flex items-center justify-center transition-opacity duration-300"
            >
              <SvgSimpleLoader
                className={isLoadingMore ? "opacity-100" : "opacity-40"}
              />
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
