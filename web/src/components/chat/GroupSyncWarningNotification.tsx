"use client";
import React from "react";
import { Notification } from "@/app/admin/settings/interfaces";
import { WarningCircle } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";

interface GroupSyncWarningNotificationProps {
  notification: Notification;
  onDismiss: (notificationId: number) => void;
}

export const GroupSyncWarningNotification: React.FC<
  GroupSyncWarningNotificationProps
> = ({ notification, onDismiss }) => {
  const router = useRouter();

  const handleNavigateToConnector = () => {
    const ccPairId = notification.additional_data?.cc_pair_id;
    if (ccPairId) {
      router.push(`/admin/connector/${ccPairId}`);
      onDismiss(notification.id);
    }
  };

  const getWarningMessage = () => {
    const warnings = notification.additional_data?.warnings;
    const connectorName =
      notification.additional_data?.connector_name || "Unknown Connector";
    const source = notification.additional_data?.source || "unknown";

    if (
      warnings?.users_without_email &&
      warnings.users_without_email.length > 0
    ) {
      return `${connectorName} (${source}) has ${warnings.users_without_email.length} users without public email addresses.`;
    }

    return `${connectorName} (${source}) has synchronization warnings.`;
  };

  const getWarningDetails = () => {
    const warnings = notification.additional_data?.warnings;
    if (
      warnings?.users_without_email &&
      warnings.users_without_email.length > 0
    ) {
      const userCount = warnings.users_without_email.length;
      const displayUsers = warnings.users_without_email.slice(0, 3);
      const hasMore = userCount > 3;

      return (
        <div className="text-xs text-text-600 mt-1">
          Users without email: {displayUsers.join(", ")}
          {hasMore && ` and ${userCount - 3} more`}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="w-72 px-4 py-3 border-b last:border-b-0 hover:bg-background-50 transition duration-150 ease-in-out">
      <div className="flex items-start">
        <div className="mt-2 flex-shrink-0 mr-3 relative">
          {notification.additional_data?.source ? (
            <SourceIcon
              sourceType={notification.additional_data.source as ValidSources}
              iconSize={24}
            />
          ) : (
            <WarningCircle size={24} className="text-amber-500" weight="fill" />
          )}
          {/* Warning indicator overlay */}
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-amber-500 rounded-full border border-white dark:border-gray-800">
            <WarningCircle size={10} className="text-white" weight="fill" />
          </div>
        </div>
        <div className="flex-grow">
          <p className="font-semibold text-sm text-text-800">
            Group Sync Warning
          </p>
          <p className="text-xs text-text-600 mt-1">{getWarningMessage()}</p>
          {getWarningDetails()}
        </div>
      </div>
      <div className="flex justify-end mt-2 space-x-2">
        <button
          onClick={handleNavigateToConnector}
          className="px-3 py-1 text-sm font-medium text-blue-600 hover:text-blue-800 transition duration-150 ease-in-out"
        >
          View Connector
        </button>
        <button
          onClick={() => onDismiss(notification.id)}
          className="px-3 py-1 text-sm font-medium text-text-600 hover:text-text-800 transition duration-150 ease-in-out"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
};
