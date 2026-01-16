"use client";

import { useMemo, useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/app/admin/settings/interfaces";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/components/user/UserProvider";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import Text from "@/refresh-components/texts/Text";
import LineItem from "@/refresh-components/buttons/LineItem";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import NotificationsPopover from "@/sections/sidebar/NotificationsPopover";
import {
  SvgBell,
  SvgExternalLink,
  SvgLogOut,
  SvgUser,
  SvgNotificationBubble,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { usePopup } from "@/components/admin/connectors/Popup";

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
  const { popup, setPopup } = usePopup();

  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  const handleLogout = () => {
    logout()
      .then((response) => {
        if (!response?.ok) {
          setPopup({ message: "Failed to logout", type: "error" });
          return;
        }

        const currentUrl = `${pathname}${
          searchParams?.toString() ? `?${searchParams.toString()}` : ""
        }`;

        const encodedRedirect = encodeURIComponent(currentUrl);

        router.push(
          `/auth/login?disableAutoRedirect=true&next=${encodedRedirect}`
        );
      })
      .catch(() => {
        setPopup({ message: "Failed to logout", type: "error" });
      });
  };

  const notificationCount = useMemo(
    () =>
      notifications?.reduce(
        (prevCount, notification) =>
          notification.dismissed ? prevCount : prevCount + 1,
        0
      ) ?? 0,
    [notifications]
  );

  return (
    <>
      {popup}

      <PopoverMenu>
        {[
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
            {`Notifications${
              notificationCount > 0 ? ` (${notificationCount})` : ""
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

export interface UserAvatarPopoverProps {
  folded?: boolean;
}

export default function UserAvatarPopover({ folded }: UserAvatarPopoverProps) {
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();
  const router = useRouter();

  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );

  const displayName = getDisplayName(user?.email, user?.personalization?.name);
  const hasNotifications =
    notifications?.some((notification) => !notification.dismissed) ?? false;

  const handlePopoverOpen = (state: boolean) => {
    if (state) {
      setPopupState("Settings");
    } else {
      setPopupState(undefined);
    }
  };

  return (
    <Popover open={!!popupState} onOpenChange={handlePopoverOpen}>
      <Popover.Trigger asChild>
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
              hasNotifications ? (
                <Section padding={0.5}>
                  <SvgNotificationBubble size={6} />
                </Section>
              ) : undefined
            }
            transient={!!popupState}
            folded={folded}
          >
            {displayName}
          </SidebarTab>
        </div>
      </Popover.Trigger>
      <Popover.Content align="end" side="right" md>
        {popupState === "Settings" && (
          <SettingsPopover
            onUserSettingsClick={() => {
              setPopupState(undefined);
              router.push("/chat/settings");
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
      </Popover.Content>
    </Popover>
  );
}
