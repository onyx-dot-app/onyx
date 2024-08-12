"use client";
import { useState, useEffect, useContext } from "react";
import { XIcon } from "../icons/icons";
import { CustomTooltip } from "../tooltip/CustomTooltip";
import { SettingsContext } from "../settings/SettingsProvider";
import Link from "next/link";

interface AnnouncementProps {
  message: string;
  id: string;
}

export function AnnouncementBanner({ message, id }: AnnouncementProps) {
  const settings = useContext(SettingsContext);

  const notifications = settings?.settings.notifications;

  if (!notifications || notifications.length === 0) return null;

  const handleDismiss = async (notificationId: number) => {
    try {
      const response = await fetch(
        `/api/settings/notifications/${notificationId}/dismiss`,
        {
          method: "POST",
        }
      );
      if (response.ok) {
        // Refresh the settings context to update the notifications list
        // You might need to implement a refresh function in your SettingsContext
        // For now, we'll assume it exists
        // settings?.refreshSettings();
      } else {
        console.error("Failed to dismiss notification");
      }
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  };

  return (
    <>
      {notifications
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
                    showTick
                    citation
                    delay={100}
                    content="Dismiss"
                  >
                    <XIcon className="h-5 w-5" />
                  </CustomTooltip>
                </button>
              </div>
            );
          }
        })}
    </>
  );
}
