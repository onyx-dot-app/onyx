"use client";

// Bottom-left floating banner: shows one banner-worthy notification at a time
// (severity WARNING or louder — connector failures, license expiry, admin
// announcements, trial notices), pageable via prev/next when more than one is
// active. Always dismissible. Anchored to the main content area's bottom-left
// corner so it never covers the sidebar. Falls back to the viewport edge when
// there is no content area.

import { usePathname, useRouter } from "next/navigation";
import { Button, Text } from "@opal/components";
import { cn, markdown } from "@opal/utils";
import { timeAgo } from "@opal/time";
import { SvgChevronLeft, SvgChevronRight, SvgX } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { isAuthPath } from "@/lib/auth/paths";
import useContainerCenter from "@/hooks/useContainerCenter";
import { getNotificationIcon, openNotificationLink } from "@/lib/notifications";
import {
  NotificationSeverity,
  NotificationType,
} from "@/lib/notifications/interfaces";
import { useBannerQueue, type BannerQueueItem } from "@/lib/banner/hooks";

// Inset from the content area's left edge, matching the card's bottom inset.
const CONTENT_INSET_PX = 8;

const VARIANT_STYLES: Record<
  NotificationSeverity,
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

// Per-type presentation extras. Variant comes from the notification's
// severity; ordering and eligibility live in useBannerQueue. Types without an
// entry get the defaults, so a new loud notification type needs no changes
// here to render.
interface BannerTypeConfig {
  sourceLabel: string;
  // Overrides the severity-derived look (admin announcements are loud enough
  // to be banners but keep their informational styling).
  variantOverride?: NotificationSeverity;
  ctaLabel?: string;
  // Replaces the copy when several undismissed notifications share the type.
  aggregate?: (count: number) => BannerContent;
}

interface BannerContent {
  title: string;
  description: string | null;
  link: string | null;
  ctaLabel: string;
}

const DEFAULT_SOURCE_LABEL = "Notification";
const DEFAULT_CTA_LABEL = "View";

function connectorAggregate(noun: string, cause: string) {
  return (count: number): BannerContent => ({
    title: `${count} connectors are ${noun}`,
    description: `Multiple connectors have ${cause}. Open the connectors page to review them.`,
    link: "/admin/indexing/status",
    ctaLabel: DEFAULT_CTA_LABEL,
  });
}

const BANNER_TYPE_CONFIG: Partial<Record<NotificationType, BannerTypeConfig>> =
  {
    [NotificationType.SYSTEM_ANNOUNCEMENT]: {
      sourceLabel: "Admin announcement",
      variantOverride: NotificationSeverity.INFO,
    },
    [NotificationType.LICENSE_EXPIRY_WARNING]: { sourceLabel: "License" },
    [NotificationType.TRIAL_ENDS_TWO_DAYS]: { sourceLabel: "Trial" },
    [NotificationType.CONNECTOR_REPEATED_ERRORS]: {
      sourceLabel: "Connectors",
      ctaLabel: "View connector",
      aggregate: connectorAggregate("failing", "repeated indexing failures"),
    },
    [NotificationType.CONNECTOR_INVALID]: {
      sourceLabel: "Connectors",
      ctaLabel: "View connector",
      aggregate: connectorAggregate("invalid", "invalid credentials"),
    },
  };

// The notification's own copy when it stands alone, the type's aggregate
// copy when it represents several.
function bannerContent(item: BannerQueueItem): BannerContent {
  const { notification, count } = item;
  const config = BANNER_TYPE_CONFIG[notification.notif_type];
  if (count > 1 && config?.aggregate) {
    return config.aggregate(count);
  }
  return {
    title: notification.title,
    description: notification.description,
    link: notification.additional_data?.link ?? null,
    ctaLabel: config?.ctaLabel ?? DEFAULT_CTA_LABEL,
  };
}

export default function BannerQueue() {
  const pathname = usePathname();
  const router = useRouter();
  const { left: contentLeft } = useContainerCenter();
  const { current, hasMultiple, goToNext, goToPrevious, dismissCurrent } =
    useBannerQueue();

  if (isAuthPath(pathname) || !current) return null;

  const notification = current.notification;
  const config = BANNER_TYPE_CONFIG[notification.notif_type];
  // An aggregate card represents every collapsed notification, so dismissing
  // it must dismiss them all — not surface them one at a time.
  const showsAggregate = current.count > 1 && Boolean(config?.aggregate);
  const styles =
    VARIANT_STYLES[config?.variantOverride ?? notification.severity];
  const Icon = getNotificationIcon(notification.notif_type);
  const { title, description, link, ctaLabel } = bannerContent(current);
  const relativeTime = timeAgo(notification.last_shown);
  const sourceLabel = config?.sourceLabel ?? DEFAULT_SOURCE_LABEL;
  // Disclose collapsed same-type siblings so dismissing the visible one
  // never surfaces the rest as a surprise.
  const footer = [
    sourceLabel,
    relativeTime,
    // Aggregate copy already states the count in the title.
    current.count > 1 && !showsAggregate ? `+${current.count - 1} more` : null,
  ]
    .filter(Boolean)
    .join(" • ");

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
        gap={1}
        padding={1}
        className="rounded-12 border border-border-01 bg-background-neutral-00 shadow-box"
      >
        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="start"
          height="fit"
          gap={1}
          padding={1.5}
          className={cn("rounded-08", styles.headerBg)}
        >
          <Icon className={cn("h-5 w-5 shrink-0 p-0.5", styles.iconClass)} />
          {/* flex-grow truncation wrapper: Text has no className, and truncate
              needs a block box, so Section (a flex container) cannot host it. */}
          <div className="flex-1 min-w-0 truncate px-0.5">
            <Text font="main-ui-action" color="text-04">
              {title}
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
            onClick={() =>
              void dismissCurrent(showsAggregate ? current.ids : undefined)
            }
            aria-label="Dismiss"
          />
        </Section>

        <Section
          flexDirection="column"
          alignItems="stretch"
          justifyContent="start"
          height="fit"
          gap={1}
          padding={2}
          className="rounded-08 bg-background-tint-01"
        >
          {description && (
            <Text font="main-ui-body" color="text-03">
              {markdown(description)}
            </Text>
          )}
          <Section
            flexDirection="row"
            alignItems="center"
            justifyContent="between"
            height="fit"
            gap={1}
          >
            <Text font="secondary-body" color="text-03">
              {footer}
            </Text>
            {link && (
              <Button
                prominence="secondary"
                size="sm"
                onClick={() => openNotificationLink(link, router)}
              >
                {ctaLabel}
              </Button>
            )}
          </Section>
        </Section>
      </Section>
    </div>
  );
}
