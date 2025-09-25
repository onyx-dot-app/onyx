"use client";

import React, { useMemo, useContext, useState } from "react";
import { UserRole } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { NavigationItem, Notification } from "@/app/admin/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useUser } from "@/components/user/UserProvider";
import { Avatar } from "@/components/ui/avatar";
import Text from "@/components-2/Text";
import Truncated from "@/components-2/Truncated";
import { SidebarButton } from "@/sections/sidebar/components";
import { MenuButton } from "@/components-2/buttons/MenuButton";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import SvgSettings from "@/icons/settings";
import SvgLogOut from "@/icons/log-out";
import SvgBell from "@/icons/bell";
import SvgX from "@/icons/x";
import { useRouter } from "next/navigation";
import Modal from "@/components-2/modals/Modal";
import { ModalIds, useModal } from "@/components-2/context/ModalContext";
import SvgUser from "@/icons/user";
import { UserSettings } from "@/app/chat/components/modal/UserSettingsModal";

function getUsernameFromEmail(email?: string): string {
  if (!email) return ANONYMOUS_USER_NAME;
  const atIndex = email.indexOf("@");
  if (atIndex <= 0) return ANONYMOUS_USER_NAME;

  return email.substring(0, atIndex);
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
  const { user, isCurator } = useUser();
  const combinedSettings = useContext(SettingsContext);
  const dropdownItems: NavigationItem[] = useMemo(
    () => combinedSettings?.enterpriseSettings?.custom_nav_items || [],
    [combinedSettings]
  );
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );
  const router = useRouter();

  const showAdminPanel =
    (!user || user.role === UserRole.ADMIN) && !removeAdminPanelLink;
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
          <div>
            <SidebarButton
              icon={({ className }) => (
                <Avatar
                  className={`h-[1.2rem] w-[1.2rem] flex items-center justify-center bg-background-neutral-inverted-00 ${className}`}
                >
                  <Text inverted>{user?.email?.[0]?.toUpperCase() || "A"}</Text>
                </Avatar>
              )}
              hideTitle={folded}
              active={!!popupState}
            >
              <Truncated disableTooltip>
                <Text text04 className="text-left">
                  {getUsernameFromEmail(user?.email)}
                </Text>
              </Truncated>
            </SidebarButton>
          </div>
        </PopoverTrigger>

        <PopoverContent align="end" side="right">
          {popupState === "Notifications" && (
            <div className="w-[20rem] h-[30rem] flex flex-col">
              <div className="flex flex-row justify-between items-center p-spacing-paragraph">
                <Text headingH2>Notifications</Text>
                <SvgX
                  className="stroke-text-05 w-[1.2rem] h-[1.2rem] hover:stroke-text-04 cursor-pointer"
                  onClick={() => setPopupState("Settings")}
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
          )}
          {popupState === "Settings" && (
            <div className="flex flex-col gap-spacing-inline overscroll-contain">
              {dropdownItems.map((item, index) => (
                <MenuButton key={index} href={item.link}>
                  {item.title}
                </MenuButton>
              ))}

              {showAdminPanel ? (
                <MenuButton href="/admin/indexing/status" icon={SvgSettings}>
                  Admin Panel
                </MenuButton>
              ) : (
                showCuratorPanel && (
                  <MenuButton href="/admin/indexing/status" icon={SvgSettings}>
                    Curator Panel
                  </MenuButton>
                )
              )}

              <MenuButton
                icon={SvgUser}
                onClick={() => {
                  setPopupState(undefined);
                  toggleModal(ModalIds.UserSettingsModal, true);
                }}
              >
                User Settings
              </MenuButton>

              <MenuButton
                icon={SvgBell}
                onClick={() => setPopupState("Notifications")}
              >
                {`Notifications ${(notifications && notifications.length) || 0 > 0 ? `(${notifications!.length})` : ""}`}
              </MenuButton>

              {showLogout && (
                <>
                  {(showCuratorPanel ||
                    showAdminPanel ||
                    dropdownItems.length > 0) && (
                    <div className="border-b mx-padding-button" />
                  )}
                  <MenuButton icon={SvgLogOut} danger onClick={handleLogout}>
                    Log out
                  </MenuButton>
                </>
              )}
            </div>
          )}
        </PopoverContent>
      </Popover>
    </>
  );
}
