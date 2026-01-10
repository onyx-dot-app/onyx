"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { Route } from "next";
import {
  Notification,
  NotificationType,
} from "@/app/admin/settings/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgSparkle, SvgRefreshCw, SvgX } from "@opal/icons";
import { IconProps } from "@opal/types";
import IconButton from "@/refresh-components/buttons/IconButton";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

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
}

export default function NotificationsPopover({
  onClose,
  onNavigate,
}: NotificationsPopoverProps) {
  const router = useRouter();
  const {
    data: notifications,
    mutate,
    isLoading,
  } = useSWR<Notification[]>("/api/notifications", errorHandlingFetcher);

  const handleNotificationClick = (notification: Notification) => {
    const link = notification.additional_data?.link;
    if (link) {
      onNavigate();
      router.push(link as Route);
    }
  };

  const handleDismiss = async (notificationId: number, e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent triggering the LineItem onClick
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
    <div className="w-[20rem] h-[32rem] flex flex-col">
      <div className="flex flex-row justify-between items-center p-4 border-b border-divider-subtle">
        <Text as="p" headingH2>
          Notifications
        </Text>
        <SvgX
          className="stroke-text-05 w-[1.2rem] h-[1.2rem] hover:stroke-text-04 cursor-pointer"
          onClick={onClose}
        />
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {isLoading ? (
          <div className="w-full h-48 flex flex-col justify-center items-center">
            <SimpleLoader className="animate-spin" />
          </div>
        ) : !notifications || notifications.length === 0 ? (
          <div className="w-full h-48 flex flex-col justify-center items-center">
            <Text as="p" text03>
              No notifications
            </Text>
          </div>
        ) : (
          <div className="flex flex-col py-2">
            {notifications.map((notification) => (
              <LineItem
                key={notification.id}
                icon={getNotificationIcon(notification.notif_type)}
                description={notification.description ?? undefined}
                onClick={() => handleNotificationClick(notification)}
                rightChildren={
                  <IconButton
                    internal
                    icon={SvgX}
                    onClick={(e) => handleDismiss(notification.id, e)}
                    tooltip="Dismiss"
                  />
                }
              >
                {notification.title}
              </LineItem>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
