"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../i18n/keys";
import React, { useEffect, useState } from "react";
import { Persona } from "@/app/admin/assistants/interfaces";
import {
  Notification,
  NotificationType,
} from "@/app/admin/settings/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { useAssistants } from "../context/AssistantsContext";
import { useUser } from "../user/UserProvider";
import { XIcon } from "../icons/icons";
import { Spinner } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import Link from "next/link";

export const Notifications = ({
  notifications,
  refreshNotifications,
  navigateToDropdown,
}: {
  notifications: Notification[];
  refreshNotifications: () => void;
  navigateToDropdown: () => void;
}) => {
  const { t } = useTranslation();
  const [showDropdown, setShowDropdown] = useState(false);
  const [isLoadingPersonas, setIsLoadingPersonas] = useState(false);
  const router = useRouter();
  const { refreshAssistants } = useAssistants();

  const { refreshUser } = useUser();
  const [personas, setPersonas] = useState<Record<number, Persona> | undefined>(
    undefined
  );

  useEffect(() => {
    const fetchPersonas = async () => {
      if (!notifications || notifications.length === 0) {
        setPersonas(undefined);
        setIsLoadingPersonas(false);
        return;
      }

      const personaNotifications = notifications.filter(
        (n) =>
          n.notif_type.toLowerCase() === NotificationType.PERSONA_SHARED &&
          n.additional_data?.persona_id !== undefined
      );

      // Если нет уведомлений с персоной, не нужно ничего загружать
      if (personaNotifications.length === 0) {
        setPersonas({});
        setIsLoadingPersonas(false);
        return;
      }

      const personaIds = personaNotifications.map(
        (n) => n.additional_data!.persona_id!
      );

      const queryParams = personaIds.map((id) => `persona_ids=${id}`).join("&");

      try {
        setIsLoadingPersonas(true);
        const response = await fetch(`/api/persona?${queryParams}`);

        if (!response.ok) {
          throw new Error(`Error fetching personas: ${response.statusText}`);
        }
        const personasData: Persona[] = await response.json();
        setPersonas(
          personasData.reduce((acc, persona) => {
            acc[persona.id] = persona;
            return acc;
          }, {} as Record<number, Persona>)
        );
      } catch (err) {
        console.error("Failed to fetch personas:", err);
        setPersonas({});
      } finally {
        setIsLoadingPersonas(false);
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

  const personaNotifications = notifications
    ? notifications.filter(
        (notification) =>
          notification.notif_type.toLowerCase() ===
            NotificationType.PERSONA_SHARED &&
          notification.additional_data?.persona_id !== undefined
      )
    : [];

  const otherNotifications = notifications
    ? notifications.filter(
        (notification) =>
          notification.notif_type.toLowerCase() !==
            NotificationType.PERSONA_SHARED ||
          notification.additional_data?.persona_id === undefined
      )
    : [];

  const sortedPersonaNotifications =
    personaNotifications && personas
      ? personaNotifications
          .filter((notification) => {
            const personaId = notification.additional_data?.persona_id;
            return personaId !== undefined && personas[personaId] !== undefined;
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
        <>
          {isLoadingPersonas && personaNotifications.length > 0 && (
            <div className="flex h-20 justify-center items-center w-72">
              <Spinner size={20} />
            </div>
          )}

          {!isLoadingPersonas &&
            sortedPersonaNotifications.map((notification) => {
              const persona = notification.additional_data?.persona_id
                ? personas?.[notification.additional_data.persona_id]
                : null;

              if (!persona) {
                return null;
              }

              return (
                <div
                  key={notification.id}
                  className="w-72 px-4 py-3 border-b last:border-b-0 hover:bg-background-50 transition duration-150 ease-in-out"
                >
                  <div className="flex items-start">
                    <div className="mt-2 flex-shrink-0 mr-3">
                      <AssistantIcon assistant={persona} size="small" />
                    </div>
                    <div className="flex-grow">
                      <p className="font-semibold text-sm text-text-800">
                        {t(k.NEW_ASSISTANT_SHARED)} {persona.name}
                      </p>
                      {persona.description && (
                        <p className="text-xs text-text-600 mt-1">
                          {persona.description}
                        </p>
                      )}
                      <div className="mt-2">
                        {persona.tools.length > 0 && (
                          <p className="text-xs text-text-500">
                            {t(k.TOOLS)}{" "}
                            {persona.tools
                              .map((tool) => tool.name)
                              .join(t(k._3))}
                          </p>
                        )}
                        {persona.document_sets.length > 0 && (
                          <p className="text-xs text-text-500">
                            {t(k.DOCUMENT_SETS3)}{" "}
                            {persona.document_sets
                              .map((set) => set.name)
                              .join(t(k._3))}
                          </p>
                        )}
                        {persona.llm_model_version_override && (
                          <p className="text-xs text-text-500">
                            {t(k.MODEL)} {persona.llm_model_version_override}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-end mt-2 space-x-2">
                    <button
                      onClick={() =>
                        handleAssistantShareAcceptance(notification, persona)
                      }
                      className="px-3 py-1 text-sm font-medium text-blue-600 hover:text-blue-800 transition duration-150 ease-in-out"
                    >
                      {t(k.CHAT1)}
                    </button>
                    <button
                      onClick={() => dismissNotification(notification.id)}
                      className="px-3 py-1 text-sm font-medium text-text-600 hover:text-text-800 transition duration-150 ease-in-out"
                    >
                      {t(k.DISMISS)}
                    </button>
                  </div>
                </div>
              );
            })}

          {otherNotifications.map((notification) => {
            const notifType = notification.notif_type.toLowerCase();

            if (
              notifType !== "reindex" &&
              notifType !== NotificationType.REINDEX_NEEDED &&
              notifType !== NotificationType.TRIAL_ENDS_TWO_DAYS
            ) {
              return null;
            }

            return (
              <div
                key={notification.id}
                className="w-72 px-4 py-3 border-b last:border-b-0 hover:bg-background-50 transition duration-150 ease-in-out"
              >
                <div className="flex flex-col text-sm text-text-800 space-y-2">
                  {notifType === "reindex" ||
                  notifType === NotificationType.REINDEX_NEEDED ? (
                    <p>
                      {t(k.YOUR_INDEX_IS_OUT_OF_DATE_WE)}{" "}
                      <Link
                        href="/admin/configuration/search"
                        className="underline text-blue-600 hover:text-blue-800"
                      >
                        {t(k.UPDATE_HERE)}
                      </Link>
                    </p>
                  ) : (
                    <p>
                      {t(k.YOUR_TRIAL_IS_ENDING_SOON_SU)}{" "}
                      <Link
                        href="/admin/billing"
                        className="underline text-blue-600 hover:text-blue-800"
                      >
                        {t(k.UPDATE_HERE)}
                      </Link>
                    </p>
                  )}
                </div>
                <div className="flex justify-end mt-2">
                  <button
                    onClick={() => dismissNotification(notification.id)}
                    className="px-3 py-1 text-sm font-medium text-text-600 hover:text-text-800 transition duration-150 ease-in-out"
                  >
                    {t(k.DISMISS)}
                  </button>
                </div>
              </div>
            );
          })}
        </>
      ) : (
        <div className="px-4 py-3 text-center text-text-600">
          {t(k.NO_NEW_NOTIFICATIONS)}
        </div>
      )}
    </div>
  );
};
