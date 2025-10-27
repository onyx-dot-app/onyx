"use client";

import { UserRole } from "@/lib/types";
import {
  SettingsContext,
  useSettingsContext,
} from "@/components/settings/SettingsProvider";

import React, { useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/app/admin/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/components/user/UserProvider";
import { Avatar } from "@/components/ui/avatar";
import Text from "@/refresh-components/texts/Text";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import SvgLogOut from "@/icons/log-out";
import SvgBell from "@/icons/bell";
import SvgX from "@/icons/x";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import SvgUser from "@/icons/user";
import { cn } from "@/lib/utils";
import { useModalContext } from "@/components/context/ModalContext";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { ToolIconSkeleton } from "@/components/icons/icons";

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
  onActionsClick: () => void;
}

function SettingsPopover({
  onUserSettingsClick,
  onNotificationsClick,
  onActionsClick,
}: SettingsPopoverProps) {
  const { user } = useUser();
  const isAdmin = user?.role === UserRole.ADMIN;
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const settings = useSettingsContext();
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
          (isAdmin ||
            settings?.settings.all_users_actions_creation_enabled !==
              false) && (
            <div key="actions" data-testid="Settings/actions">
              <MenuButton icon={ToolIconSkeleton} onClick={onActionsClick}>
                Actions
              </MenuButton>
            </div>
          ),
          <div key="user-settings" data-testid="Settings/user-settings">
            <MenuButton icon={SvgUser} onClick={onUserSettingsClick}>
              User Settings
            </MenuButton>
          </div>,
          <MenuButton
            key="notifications"
            icon={SvgBell}
            onClick={onNotificationsClick}
          >
            {`Notifications ${
              notifications && notifications.length > 0
                ? `(${notifications.length})`
                : ""
            }`}
          </MenuButton>,
          null,
          showLogout && (
            <MenuButton
              key="log-out"
              icon={SvgLogOut}
              danger
              onClick={handleLogout}
            >
              Log out
            </MenuButton>
          ),
        ]}
      </PopoverMenu>
    </>
  );
}

interface NotificationsPopoverProps {
  onClose: () => void;
}

function NotificationsPopover({ onClose }: NotificationsPopoverProps) {
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );

  return (
    <div className="w-[20rem] h-[30rem] flex flex-col">
      <div className="flex flex-row justify-between items-center p-4">
        <Text headingH2>Notifications</Text>
        <SvgX
          className="stroke-text-05 w-[1.2rem] h-[1.2rem] hover:stroke-text-04 cursor-pointer"
          onClick={onClose}
        />
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-4 flex flex-col gap-2 items-center">
        {!notifications || notifications.length === 0 ? (
          <div className="w-full h-full flex flex-col justify-center items-center">
            <Text>No notifications</Text>
          </div>
        ) : (
          <div className="w-full flex flex-col gap-2">
            {notifications?.map((notification, index) => (
              <Text key={index}>{notification.notif_type}</Text>
            ))}
          </div>
        )}
      </div>
    </div>
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
  const { setShowUserSettingsModal } = useModalContext();

  const displayName = getDisplayName(user?.email, user?.personalization?.name);

  return (
    <Popover
      open={!!popupState}
      onOpenChange={(state) =>
        state ? setPopupState("Settings") : setPopupState(undefined)
      }
    >
      <PopoverTrigger asChild>
        <div id="onyx-user-dropdown">
          <SidebarTab
            leftIcon={({ className }) => (
              <Avatar
                className={cn(
                  "flex items-center justify-center bg-background-neutral-inverted-00",
                  className,
                  "w-5 h-5"
                )}
              >
                <Text inverted secondaryBody>
                  {displayName[0]?.toUpperCase()}
                </Text>
              </Avatar>
            )}
            active={!!popupState}
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
              setShowUserSettingsModal(true);
            }}
            onNotificationsClick={() => setPopupState("Notifications")}
            onActionsClick={() => (window.location.href = "/actions")}
          />
        )}
        {popupState === "Notifications" && (
          <NotificationsPopover onClose={() => setPopupState("Settings")} />
        )}
      </PopoverContent>
    </Popover>
  );
}
