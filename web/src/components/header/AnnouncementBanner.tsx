"use client";
import { useState, useEffect, useContext } from "react";
import { XIcon } from "../icons/icons";
import { SettingsContext } from "../settings/SettingsProvider";
import Link from "next/link";
import Cookies from "js-cookie";
import { CustomTooltip } from "../CustomTooltip";

const DISMISSED_NOTIFICATION_COOKIE_PREFIX = "dismissed_notification_";
const COOKIE_EXPIRY_DAYS = 1;

export function AnnouncementBanner() {
  const settings = useContext(SettingsContext);
  const [localNotifications, setLocalNotifications] = useState(
    settings?.settings.notifications || []
  );

  useEffect(() => {
    const filteredNotifications = (
      settings?.settings.notifications || []
    ).filter(
      (notification) =>
        !Cookies.get(
          `${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${notification.id}`
        )
    );
    setLocalNotifications(filteredNotifications);
  }, [settings?.settings.notifications]);

  if (!localNotifications || localNotifications.length === 0) return null;

  const handleDismiss = async (notificationId: number) => {
    try {
      const response = await fetch(
        `/api/settings/notifications/${notificationId}/dismiss`,
        {
          method: "POST",
        }
      );
      if (response.ok) {
        Cookies.set(
          `${DISMISSED_NOTIFICATION_COOKIE_PREFIX}${notificationId}`,
          "true",
          { expires: COOKIE_EXPIRY_DAYS }
        );
        setLocalNotifications((prevNotifications) =>
          prevNotifications.filter(
            (notification) => notification.id !== notificationId
          )
        );
      } else {
        console.error("Failed to dismiss notification");
      }
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  };

  return (
    <>
      {localNotifications
        .filter((notification) => !notification.dismissed)
        .map((notification) => {
          if (notification.notif_type == "reindex") {
            return (
              <div
                key={notification.id}
                className="absolute top-0 left-1/2 transform -translate-x-1/2 bg-blue-600 rounded-sm text-white px-4 pr-8 py-3 mx-auto"
              >
                <p className="text-center">
                  Your index is out of date - we strongly recommend updating
                  your search settings.{" "}
                  <Link
                    href={"/admin/configuration/search"}
                    className="ml-2 underline cursor-pointer"
                  >
                    Update here
                  </Link>
                </p>
                <button
                  onClick={() => handleDismiss(notification.id)}
                  className="absolute top-0 right-0 mt-2 mr-2"
                  aria-label="Dismiss"
                >
                  <CustomTooltip
                    delayDuration={100}
                    trigger={<XIcon className="h-5 w-5" />}
                  >
                    <p>Dismiss</p>
                  </CustomTooltip>
                </button>
              </div>
            );
          }
          return null;
        })}
    </>
  );
}
