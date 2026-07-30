"use client";

// Bottom-left floating banner: shows one banner-worthy notification at a time
// (admin site-wide announcement, license expiry warning, trial-ending notice),
// pageable via prev/next when more than one is active. Always dismissible.
// Anchored to the main content area's bottom-left corner so it never covers
// the sidebar. Falls back to the viewport edge when there is no content area.

import { usePathname } from "next/navigation";
import { Button, Text } from "@opal/components";
import { cn, markdown } from "@opal/utils";
import { timeAgo } from "@opal/time";
import { SvgChevronLeft, SvgChevronRight, SvgX } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { isAuthPath } from "@/lib/auth/paths";
import useContainerCenter from "@/hooks/useContainerCenter";
import { getNotificationIcon } from "@/lib/notifications";
import {
  NotificationType,
  type Notification,
} from "@/lib/notifications/interfaces";
import {
  LICENSE_EXPIRY_ERROR_THRESHOLD,
  licenseExpirySeverity,
  useBannerQueue,
} from "@/lib/banner/hooks";

// Inset from the content area's left edge, matching the card's bottom inset.
const CONTENT_INSET_PX = 8;

type BannerVariant = "info" | "warning" | "error";

const VARIANT_STYLES: Record<
  BannerVariant,
  { headerBg: string; iconClass: string }
> = {
  info: { headerBg: "bg-status-info-00", iconClass: "stroke-status-info-05" },
  warning: {
    headerBg: "bg-status-warning-00",
    iconClass: "stroke-status-warning-05",
  },
  error: {
    headerBg: "bg-status-error-00",
    iconClass: "stroke-status-error-05",
  },
};

function bannerVariant(notification: Notification): BannerVariant {
  switch (notification.notif_type) {
    case NotificationType.TRIAL_ENDS_TWO_DAYS:
      return "warning";
    case NotificationType.LICENSE_EXPIRY_WARNING:
      return licenseExpirySeverity(notification) >=
        LICENSE_EXPIRY_ERROR_THRESHOLD
        ? "error"
        : "warning";
    default:
      return "info";
  }
}

function bannerSourceLabel(notifType: NotificationType): string {
  switch (notifType) {
    case NotificationType.SYSTEM_ANNOUNCEMENT:
      return "Admin announcement";
    case NotificationType.LICENSE_EXPIRY_WARNING:
      return "License";
    case NotificationType.TRIAL_ENDS_TWO_DAYS:
      return "Trial";
    default:
      return "Notification";
  }
}

export default function BannerQueue() {
  const pathname = usePathname();
  const { left: contentLeft } = useContainerCenter();
  const { current, hasMultiple, goToNext, goToPrevious, dismissCurrent } =
    useBannerQueue();

  if (isAuthPath(pathname) || !current) return null;

  const styles = VARIANT_STYLES[bannerVariant(current)];
  const Icon = getNotificationIcon(current.notif_type);
  const relativeTime = timeAgo(current.last_shown);
  const footer = relativeTime
    ? `${bannerSourceLabel(current.notif_type)} • ${relativeTime}`
    : bannerSourceLabel(current.notif_type);

  return (
    <div
      className="fixed bottom-2 left-2 z-toast w-[400px] max-w-[calc(100vw-1rem)]"
      style={
        contentLeft !== null
          ? { left: contentLeft + CONTENT_INSET_PX }
          : undefined
      }
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        justifyContent="start"
        height="fit"
        gap={0.25}
        padding={0.25}
        className="rounded-12 border border-border-01 bg-background-neutral-00 shadow-box"
      >
        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="start"
          height="fit"
          gap={0.25}
          padding={0.375}
          className={cn("rounded-08", styles.headerBg)}
        >
          <Icon className={cn("h-5 w-5 shrink-0 p-0.5", styles.iconClass)} />
          {/* flex-grow truncation wrapper: Text has no className, and truncate
              needs a block box, so Section (a flex container) cannot host it. */}
          <div className="flex-1 min-w-0 truncate px-0.5">
            <Text font="main-ui-action" color="text-04">
              {current.title}
            </Text>
          </div>
          {hasMultiple && (
            <>
              <Button
                icon={SvgChevronLeft}
                prominence="internal"
                size="sm"
                onClick={goToPrevious}
                aria-label="Previous banner"
              />
              <Button
                icon={SvgChevronRight}
                prominence="internal"
                size="sm"
                onClick={goToNext}
                aria-label="Next banner"
              />
            </>
          )}
          <Button
            icon={SvgX}
            prominence="internal"
            size="sm"
            onClick={() => void dismissCurrent()}
            aria-label="Dismiss"
          />
        </Section>

        <Section
          flexDirection="column"
          alignItems="stretch"
          justifyContent="start"
          height="fit"
          gap={0.25}
          padding={0.5}
          className="rounded-08 bg-background-tint-01"
        >
          {current.description && (
            <Text font="main-ui-body" color="text-03">
              {markdown(current.description)}
            </Text>
          )}
          <Text font="secondary-body" color="text-03">
            {footer}
          </Text>
        </Section>
      </Section>
    </div>
  );
}
