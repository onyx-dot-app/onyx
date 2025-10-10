"use client";

import React, { useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/app/admin/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/components/user/UserProvider";
import { Avatar } from "@/components/ui/avatar";
import Text from "@/refresh-components/Text";
import NavigationTab from "@/refresh-components/buttons/NavigationTab";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import SvgSettings from "@/icons/settings";
import SvgLogOut from "@/icons/log-out";
import SvgBell from "@/icons/bell";
import SvgX from "@/icons/x";
import { useRouter } from "next/navigation";
import SvgUser from "@/icons/user";
import { cn } from "@/lib/utils";
import { useModalContext } from "@/components/context/ModalContext";

function getUsernameFromEmail(email?: string): string {
  if (!email) return ANONYMOUS_USER_NAME;
  const atIndex = email.indexOf("@");
  if (atIndex <= 0) return ANONYMOUS_USER_NAME;

  return email.substring(0, atIndex);
}

interface SettingsPopoverProps {
  removeAdminPanelLink?: boolean;
  onUserSettingsClick: () => void;
  onNotificationsClick: () => void;
}

function SettingsPopover({
  removeAdminPanelLink,
  onUserSettingsClick,
  onNotificationsClick,
}: SettingsPopoverProps) {
  const { user, isAdmin, isCurator } = useUser();
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );
  const router = useRouter();

  const showAdminPanel = (!user || isAdmin) && !removeAdminPanelLink;
  const showCuratorPanel = user && isCurator;
  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  async function handleLogout() {
    const isSuccess = await logout();

    if (!isSuccess) {
      alert("Failed to logout");
      return;
    }

    router.push(
      `/auth/login?next=${encodeURIComponent(
        window.location.pathname + window.location.search
      )}`
    );
  }

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
          showAdminPanel && (
            <NavigationTab
              key="admin-panel"
              href="/admin/indexing/status"
              icon={SvgSettings}
            >
              Admin Panel
            </NavigationTab>
          ),
          showCuratorPanel && (
            <NavigationTab
              key="curator-panel"
              href="/admin/indexing/status"
              icon={SvgSettings}
            >
              Curator Panel
            </NavigationTab>
          ),
          <div key="user-settings" data-testid="Settings/user-settings">
            <NavigationTab icon={SvgUser} onClick={onUserSettingsClick}>
              User Settings
            </NavigationTab>
          </div>,
          <NavigationTab
            key="notifications"
            icon={SvgBell}
            onClick={onNotificationsClick}
          >
            {`Notifications ${
              notifications && notifications.length > 0
                ? `(${notifications.length})`
                : ""
            }`}
          </NavigationTab>,
          null,
          showLogout && (
            <NavigationTab
              key="log-out"
              icon={SvgLogOut}
              danger
              onClick={handleLogout}
            >
              Log out
            </NavigationTab>
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
      <div className="flex flex-row justify-between items-center p-spacing-paragraph">
        <Text headingH2>Notifications</Text>
        <SvgX
          className="stroke-text-05 w-[1.2rem] h-[1.2rem] hover:stroke-text-04 cursor-pointer"
          onClick={onClose}
        />
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-spacing-paragraph flex flex-col gap-spacing-interline items-center">
        {!notifications || notifications.length === 0 ? (
          <div className="w-full h-full flex flex-col justify-center items-center">
            <Text>No notifications</Text>
          </div>
        ) : (
          <div className="w-full flex flex-col gap-spacing-interline">
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
  removeAdminPanelLink?: boolean;
}

export default function Settings({
  folded,
  removeAdminPanelLink,
}: SettingsProps) {
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();
  const { setShowUserSettingsModal } = useModalContext();

  const username = getUsernameFromEmail(user?.email);

  return (
    <Popover
      open={!!popupState}
      onOpenChange={(state) =>
        state ? setPopupState("Settings") : setPopupState(undefined)
      }
    >
      <PopoverTrigger asChild>
        <div className="flex flex-col w-full h-full" id="onyx-user-dropdown">
          <NavigationTab
            className="!w-full"
            iconClassName="w-5 h-5"
            icon={({ className }) => (
              <Avatar
                className={cn(
                  "flex items-center justify-center bg-background-neutral-inverted-00",
                  className
                )}
              >
                <Text inverted secondaryBody>
                  {username[0]?.toUpperCase()}
                </Text>
              </Avatar>
            )}
            active={!!popupState}
            folded={folded}
            highlight
          >
            {username}
          </NavigationTab>
        </div>
      </PopoverTrigger>
      <PopoverContent align="end" side="right">
        {popupState === "Settings" && (
          <SettingsPopover
            removeAdminPanelLink={removeAdminPanelLink}
            onUserSettingsClick={() => {
              setPopupState(undefined);
              setShowUserSettingsModal(true);
            }}
            onNotificationsClick={() => setPopupState("Notifications")}
          />
        )}
        {popupState === "Notifications" && (
          <NotificationsPopover onClose={() => setPopupState("Settings")} />
        )}
      </PopoverContent>
    </Popover>
  );
}
