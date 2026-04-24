"use client";

import { useState } from "react";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/interfaces/settings";
import useSWR, { preload } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { checkUserIsNoAuthUser, getUserDisplayName, logout } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SidebarTab, LineItemButton } from "@opal/components";
import NotificationsPopover from "@/sections/sidebar/NotificationsPopover";
import {
  SvgBell,
  SvgHelpCircle,
  SvgLogOut,
  SvgSliders,
  SvgUser,
  SvgNotificationBubble,
} from "@opal/icons";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import packageJson from "../../../package.json";
import { toast } from "@/hooks/useToast";
import useAppFocus from "@/hooks/useAppFocus";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";

interface SettingsPopoverProps {
  onUserSettingsClick: () => void;
  onOpenNotifications: () => void;
}

function SettingsPopover({
  onUserSettingsClick,
  onOpenNotifications,
}: SettingsPopoverProps) {
  const { user } = useUser();
  const { data: notifications } = useSWR<Notification[]>(
    SWR_KEYS.notifications,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const undismissedCount =
    notifications?.filter((n) => !n.dismissed).length ?? 0;
  const isAnonymousUser =
    user?.is_anonymous_user || checkUserIsNoAuthUser(user?.id ?? "");
  const showLogout = user && !isAnonymousUser && !LOGOUT_DISABLED;
  const showLogin = isAnonymousUser;

  const handleLogin = () => {
    const currentUrl = `${pathname}${
      searchParams?.toString() ? `?${searchParams.toString()}` : ""
    }`;
    const encodedRedirect = encodeURIComponent(currentUrl);
    router.push(`/auth/login?next=${encodedRedirect}`);
  };

  const handleLogout = () => {
    logout()
      .then((response) => {
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
      })

      .catch(() => {
        toast.error("Failed to logout");
      });
  };

  return (
    <>
      <PopoverMenu>
        {[
          <div key="user-settings" data-testid="Settings/user-settings">
            <LineItemButton
              sizePreset="main-ui"
              variant="section"
              icon={SvgSliders}
              title="Settings"
              href="/app/settings"
              onClick={onUserSettingsClick}
            />
          </div>,
          <LineItemButton
            key="notifications"
            sizePreset="main-ui"
            variant="section"
            icon={SvgBell}
            title={`Notifications${
              undismissedCount > 0 ? ` (${undismissedCount})` : ""
            }`}
            onClick={onOpenNotifications}
          />,
          <LineItemButton
            key="help-faq"
            sizePreset="main-ui"
            variant="section"
            icon={SvgHelpCircle}
            title="Help & FAQ"
            href="https://docs.onyx.app"
            target="_blank"
          />,
          showLogin && (
            <LineItemButton
              key="log-in"
              sizePreset="main-ui"
              variant="section"
              icon={SvgUser}
              title="Log in"
              onClick={handleLogin}
            />
          ),
          showLogout && (
            <LineItemButton
              key="log-out"
              sizePreset="main-ui"
              variant="section"
              icon={SvgLogOut}
              title="Log Out"
              onClick={handleLogout}
            />
          ),
          null,
          <div key="version" className="p-2">
            <Content
              sizePreset="secondary"
              variant="body"
              prominence="muted"
              title={`${packageJson.name} v${packageJson.version}`}
            />
          </div>,
        ]}
      </PopoverMenu>
    </>
  );
}

export interface SettingsProps {
  folded?: boolean;
  onShowBuildIntro?: () => void;
}

export default function AccountPopover({
  folded,
  onShowBuildIntro,
}: SettingsProps) {
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();
  const appFocus = useAppFocus();
  const vectorDbEnabled = useVectorDbEnabled();

  // Fetch notifications for display
  // The GET endpoint also triggers a refresh if release notes are stale
  const { data: notifications } = useSWR<Notification[]>(
    SWR_KEYS.notifications,
    errorHandlingFetcher
  );

  const userDisplayName = getUserDisplayName(user);
  const undismissedCount =
    notifications?.filter((n) => !n.dismissed).length ?? 0;
  const hasNotifications = undismissedCount > 0;

  const handlePopoverOpen = (state: boolean) => {
    if (state) {
      // Prefetch user settings data when popover opens for instant modal display
      preload("/api/user/pats", errorHandlingFetcher);
      preload("/api/federated/oauth-status", errorHandlingFetcher);
      if (vectorDbEnabled) {
        preload("/api/manage/connector-status", errorHandlingFetcher);
      }
      preload("/api/llm/provider", errorHandlingFetcher);
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
            icon={() => (
              <div className="w-[16px] flex flex-col justify-center items-center">
                <UserAvatar user={user} size={18} />
              </div>
            )}
            rightChildren={
              hasNotifications ? (
                <Section padding={0.5}>
                  <SvgNotificationBubble size={6} />
                </Section>
              ) : undefined
            }
            type="button"
            selected={!!popupState || appFocus.isUserSettings()}
            folded={folded}
          >
            {userDisplayName}
          </SidebarTab>
        </div>
      </Popover.Trigger>

      <Popover.Content
        align="end"
        side="right"
        width={popupState === "Notifications" ? "xl" : "md"}
      >
        {popupState === "Settings" && (
          <SettingsPopover
            onUserSettingsClick={() => {
              setPopupState(undefined);
            }}
            onOpenNotifications={() => setPopupState("Notifications")}
          />
        )}
        {popupState === "Notifications" && (
          <NotificationsPopover
            onClose={() => setPopupState("Settings")}
            onNavigate={() => setPopupState(undefined)}
            onShowBuildIntro={onShowBuildIntro}
          />
        )}
      </Popover.Content>
    </Popover>
  );
}
