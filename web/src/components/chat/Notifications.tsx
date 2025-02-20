import React, { useEffect, useState } from "react";
import useSWR from "swr";
import { Persona } from "@/app/admin/assistants/interfaces";
import {
  Notification,
  NotificationType,
} from "@/app/admin/settings/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { addAssistantToList } from "@/lib/assistants/updateAssistantPreferences";
import { useAssistants } from "../context/AssistantsContext";
import { useUser } from "../user/UserProvider";
import { XIcon } from "../icons/icons";
import { Spinner } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";

export const Notifications = ({
  notifications,
  refreshNotifications,
  navigateToDropdown,
}: {
  notifications: Notification[];
  refreshNotifications: () => void;
  navigateToDropdown: () => void;
}) => {
  const [showDropdown, setShowDropdown] = useState(false);
  const router = useRouter();
  const { refreshAssistants } = useAssistants();

  const { refreshUser } = useUser();
  const [personas, setPersonas] = useState<Record<number, Persona> | undefined>(
    undefined
  );

  useEffect(() => {
    const fetchPersonas = async () => {
      if (notifications) {
        const personaIds = notifications
          .filter(
            (n) =>
              n.notif_type.toLowerCase() === "persona_shared" &&
              n.additional_data?.persona_id !== undefined
          )
          .map((n) => n.additional_data!.persona_id!);

        if (personaIds.length > 0) {
          const queryParams = personaIds
            .map((id) => `persona_ids=${id}`)
            .join("&");
          try {
            const response = await fetch(`/api/persona?${queryParams}`);

            if (!response.ok) {
              throw new Error(
                `Error fetching personas: ${response.statusText}`
              );
            }
            const personasData: Persona[] = await response.json();
            setPersonas(
              personasData.reduce(
                (acc, persona) => {
                  acc[persona.id] = persona;
                  return acc;
                },
                {} as Record<number, Persona>
              )
            );
          } catch (err) {
            console.error("Failed to fetch personas:", err);
          }
        }
      }
    };

    fetchPersonas();
  }, [notifications]);

  const dismissNotification = async (notificationId: number) => {
    try {
      await fetch(`/api/notifications/${notificationId}/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      refreshNotifications();
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  };

  const handleAssistantShareAcceptance = async (
    notification: Notification,
    persona: Persona
  ) => {
    await dismissNotification(notification.id);
    await refreshUser();
    await refreshAssistants();
    router.push(`/chat?assistantId=${persona.id}`);
  };

  const sortedNotifications = notifications
    ? notifications
        .filter((notification) => {
          const personaId = notification.additional_data?.persona_id;
          return (
            personaId !== undefined &&
            personas &&
            personas[personaId] !== undefined
          );
        })
        .sort(
          (a, b) =>
            new Date(b.time_created).getTime() -
            new Date(a.time_created).getTime()
        )
    : [];

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        showDropdown &&
        !(event.target as Element).closest(".notification-dropdown")
      ) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showDropdown]);
  return (
    <div className="w-full">
      <button
        onClick={navigateToDropdown}
        className="absolute right-2 text-text-600 hover:text-text-900 transition-colors duration-150 ease-in-out rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-label="Back"
      >
        <XIcon className="w-5 h-5" />
      </button>

      {notifications && notifications.length > 0 ? (
        sortedNotifications.length > 0 && personas ? (
          sortedNotifications
            .filter(
              (notification) =>
                notification.notif_type === NotificationType.PERSONA_SHARED
            )
            .map((notification) => {
              const persona = notification.additional_data?.persona_id
                ? personas[notification.additional_data.persona_id]
                : null;

              return (
                <div
                  key={notification.id}
                  className="w-72 px-4 py-3 border-b last:border-b-0 hover:bg-background-50 transition duration-150 ease-in-out"
                >
                  <div className="flex items-start">
                    {persona && (
                      <div className="mt-2 flex-shrink-0 mr-3">
                        <AssistantIcon assistant={persona} size="small" />
                      </div>
                    )}
                    <div className="flex-grow">
                      <p className="font-semibold text-sm text-text-800">
                        New Assistant Shared: {persona?.name}
                      </p>
                      {persona?.description && (
                        <p className="text-xs text-text-600 mt-1">
                          {persona.description}
                        </p>
                      )}
                      {persona && (
                        <div className="mt-2">
                          {persona.tools.length > 0 && (
                            <p className="text-xs text-text-500">
                              Tools:{" "}
                              {persona.tools
                                .map((tool) => tool.name)
                                .join(", ")}
                            </p>
                          )}
                          {persona.document_sets.length > 0 && (
                            <p className="text-xs text-text-500">
                              Document Sets:{" "}
                              {persona.document_sets
                                .map((set) => set.name)
                                .join(", ")}
                            </p>
                          )}
                          {persona.llm_model_version_override && (
                            <p className="text-xs text-text-500">
                              Model: {persona.llm_model_version_override}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex justify-end mt-2 space-x-2">
                    <button
                      onClick={() =>
                        handleAssistantShareAcceptance(notification, persona!)
                      }
                      className="px-3 py-1 text-sm font-medium text-blue-600 hover:text-blue-800 transition duration-150 ease-in-out"
                    >
                      Chat
                    </button>
                    <button
                      onClick={() => dismissNotification(notification.id)}
                      className="px-3 py-1 text-sm font-medium text-text-600 hover:text-text-800 transition duration-150 ease-in-out"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              );
            })
        ) : (
          <div className="flex h-20 justify-center items-center w-72">
            <Spinner size={20} />
          </div>
        )
      ) : (
        <div className="px-4 py-3 text-center text-text-600">
          No new notifications
        </div>
      )}
    </div>
  );
};
