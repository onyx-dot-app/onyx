"use client";

import { useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/app/admin/settings/interfaces";
import useSWR, { preload } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/components/user/UserProvider";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import UserSettings from "@/sections/sidebar/Settings/UserSettings";
import NotificationsPopover from "@/sections/sidebar/Settings/NotificationsPopover";

import {
  SvgBell,
  SvgExternalLink,
  SvgLogOut,
  SvgUser,
  SvgNotificationBubble,
} from "@opal/icons";

function getDisplayName(email?: string, personalName?: string): string {
  // Prioritize custom personal name if set
  if (personalName && personalName.trim()) {
    return personalName.trim();
  }

  // Fallback to email-derived username
  if (!email) return ANONYMOUS_USER_NAME;
  const atIndex = email.indexOf("@");
  if (atIndex <= 0) return ANONYMOUS_USER_NAME;

  return email.substring(0, atIndex);
}

interface SettingsPopoverProps {
  onUserSettingsClick: () => void;
  onNotificationsClick: () => void;
}

function SettingsPopover({
  onUserSettingsClick,
  onNotificationsClick,
}: SettingsPopoverProps) {
  const { user } = useUser();
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  const handleLogout = () => {
    logout().then((response) => {
      if (!response?.ok) {
        alert("Failed to logout");
        return;
      }

      const currentUrl = `${pathname}${
        searchParams?.toString() ? `?${searchParams.toString()}` : ""
      }`;

      const encodedRedirect = encodeURIComponent(currentUrl);

      router.push(
        `/auth/login?disableAutoRedirect=true&next=${encodedRedirect}`
      );
    });
  };

  return (
    <>
      <PopoverMenu>
        {[
          // TODO (@raunakab):
          // Not sure what this does; leave it out for now.
          // ...dropdownItems.map((item, index) => (
          //   <NavigationTab key={index} href={item.link}>
          //     {item.title}
          //   </NavigationTab>
          // )),
          <div key="user-settings" data-testid="Settings/user-settings">
            <LineItem icon={SvgUser} onClick={onUserSettingsClick}>
              User Settings
            </LineItem>
          </div>,
          <LineItem
            key="notifications"
            icon={SvgBell}
            onClick={onNotificationsClick}
          >
            {`Notifications ${
              notifications && notifications.length > 0
                ? `(${notifications.length})`
                : ""
            }`}
          </LineItem>,
          <LineItem
            key="help-faq"
            icon={SvgExternalLink}
            onClick={() => window.open("https://docs.onyx.app", "_blank")}
          >
            Help & FAQ
          </LineItem>,
          null,
          showLogout && (
            <LineItem
              key="log-out"
              icon={SvgLogOut}
              danger
              onClick={handleLogout}
            >
              Log out
            </LineItem>
          ),
        ]}
      </PopoverMenu>
    </>
  );
}

export interface SettingsProps {
  folded?: boolean;
}

export default function Settings({ folded }: SettingsProps) {
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();
  const userSettingsModal = useCreateModal();

  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );

  const displayName = getDisplayName(user?.email, user?.personalization?.name);
  const hasNotifications = notifications && notifications.length > 0;

  const handlePopoverOpen = (state: boolean) => {
    if (state) {
      // Prefetch user settings data when popover opens for instant modal display
      preload("/api/user/pats", errorHandlingFetcher);
      preload("/api/federated/oauth-status", errorHandlingFetcher);
      preload("/api/manage/connector-status", errorHandlingFetcher);
      preload("/api/llm/provider", errorHandlingFetcher);
      setPopupState("Settings");
    } else {
      setPopupState(undefined);
    }
  };

  return (
    <>
      <userSettingsModal.Provider>
        <UserSettings />
      </userSettingsModal.Provider>

      <Popover open={!!popupState} onOpenChange={handlePopoverOpen}>
        <PopoverTrigger asChild>
          <div id="onyx-user-dropdown">
            <SidebarTab
              leftIcon={({ className }) => (
                <InputAvatar
                  className={cn(
                    "flex items-center justify-center bg-background-neutral-inverted-00",
                    className,
                    "w-5 h-5"
                  )}
                >
                  <Text as="p" inverted secondaryBody>
                    {displayName[0]?.toUpperCase()}
                  </Text>
                </InputAvatar>
              )}
              rightChildren={
                hasNotifications && (
                  <div className="w-6 h-6 flex items-center justify-center">
                    <SvgNotificationBubble size={6} />
                  </div>
                )
              }
              transient={!!popupState}
              folded={folded}
            >
              {displayName}
            </SidebarTab>
          </div>
        </PopoverTrigger>
        <PopoverContent align="end" side="right">
          {popupState === "Settings" && (
            <SettingsPopover
              onUserSettingsClick={() => {
                setPopupState(undefined);
                userSettingsModal.toggle(true);
              }}
              onNotificationsClick={() => setPopupState("Notifications")}
            />
          )}
          {popupState === "Notifications" && (
            <NotificationsPopover
              onClose={() => setPopupState("Settings")}
              onNavigate={() => setPopupState(undefined)}
            />
          )}
        </PopoverContent>
      </Popover>
    </>
  );
}
