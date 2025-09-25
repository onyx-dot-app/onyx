"use client";

import React, { useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/app/admin/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/components/user/UserProvider";
import { Avatar } from "@/components/ui/avatar";
import Text from "@/components-2/Text";
import { NavigationTab } from "@/components-2/buttons/NavigationTab";
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
import Modal from "@/components-2/modals/Modal";
import { ModalIds, useModal } from "@/components-2/context/ModalContext";
import SvgUser from "@/icons/user";
import { UserSettings } from "@/app/chat/components/modal/UserSettingsModal";
import { cn } from "@/lib/utils";

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
      `/auth/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
    );
  }

  return (
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
        <NavigationTab
          key="user-settings"
          icon={SvgUser}
          onClick={onUserSettingsClick}
        >
          User Settings
        </NavigationTab>,
        <NavigationTab
          key="notifications"
          icon={SvgBell}
          onClick={onNotificationsClick}
        >
          {`Notifications ${(notifications && notifications.length) || 0 > 0 ? `(${notifications!.length})` : ""}`}
        </NavigationTab>,
        showLogout && null,
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
  const { toggleModal } = useModal();
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();

  const username = getUsernameFromEmail(user?.email);

  return (
    <>
      <Modal id={ModalIds.UserSettingsModal} title="User Settings" mini>
        <UserSettings
          setPopup={() => toggleModal(ModalIds.UserSettingsModal, false)}
          llmProviders={[]}
          onClose={() => {}}
          defaultModel={null}
          ccPairs={[]}
          federatedConnectors={[]}
          refetchFederatedConnectors={() => {}}
        />
      </Modal>

      <Popover
        open={!!popupState}
        onOpenChange={(state) =>
          state ? setPopupState("Settings") : setPopupState(undefined)
        }
      >
        <PopoverTrigger asChild>
          <div className="flex flex-col w-full h-full">
            <NavigationTab
              className="!w-full"
              icon={({ className }) => (
                <Avatar
                  className={cn(
                    "flex items-center justify-center bg-background-neutral-inverted-00",
                    className
                  )}
                >
                  <Text inverted>{username[0]?.toUpperCase()}</Text>
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
                toggleModal(ModalIds.UserSettingsModal, true);
              }}
              onNotificationsClick={() => setPopupState("Notifications")}
            />
          )}
          {popupState === "Notifications" && (
            <NotificationsPopover onClose={() => setPopupState("Settings")} />
          )}
        </PopoverContent>
      </Popover>
    </>
  );
}
