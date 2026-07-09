"use client";

import { useState } from "react";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { preload } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  checkUserIsNoAuthUser,
  getUserDisplayName,
  getUserEmail,
  logout,
} from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { Popover, PopoverMenu } from "@opal/components";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SidebarTab, LineItemButton } from "@opal/components";
import NotificationsPopover from "@/sections/sidebar/NotificationsPopover";
import {
  SvgBell,
  SvgExternalLink,
  SvgHelpCircle,
  SvgLogOut,
  SvgSliders,
  SvgUser,
  SvgNotificationBubble,
} from "@opal/icons";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import useAppFocus from "@/hooks/useAppFocus";
import { useSettings } from "@/lib/settings/hooks";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { useNotificationSummary } from "@/hooks/useNotifications";
import { SvgOnyxLogo } from "@opal/logos";
import { markdown } from "@opal/utils";

interface SettingsPopoverProps {
  onUserSettingsClick: () => void;
  onOpenNotifications: () => void;
  undismissedCount: number;
}

function SettingsPopover({
  onUserSettingsClick,
  onOpenNotifications,
  undismissedCount,
}: SettingsPopoverProps) {
  const { user } = useUser();
  const settings = useSettings();
  const enterpriseSettings = settings.enterprise;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
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
    <PopoverMenu>
      {[
        <div key="user-email" className="p-2">
          <Content sizePreset="main-ui" title={getUserEmail(user)} />
        </div>,
        null,
        <div key="user-settings" data-testid="Settings/user-settings">
          <LineItemButton
            sizePreset="main-ui"
            variant="section"
            rounding="sm"
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
          rounding="sm"
          icon={SvgBell}
          title="Notifications"
          onClick={onOpenNotifications}
          rightChildren={
            undismissedCount ? (
              <SvgNotificationBubble count={undismissedCount} />
            ) : undefined
          }
        />,
        <LineItemButton
          key="help-faq"
          sizePreset="main-ui"
          variant="section"
          rounding="sm"
          icon={SvgHelpCircle}
          title="Help & FAQ"
          href="https://docs.onyx.app"
          target="_blank"
        />,
        enterpriseSettings?.custom_help_link_url && (
          <LineItemButton
            key="custom-help-link"
            sizePreset="main-ui"
            variant="section"
            rounding="sm"
            icon={SvgExternalLink}
            title={
              enterpriseSettings.custom_help_link_label ||
              enterpriseSettings.custom_help_link_url
            }
            href={enterpriseSettings.custom_help_link_url}
            target="_blank"
          />
        ),
        showLogin && (
          <LineItemButton
            key="log-in"
            sizePreset="main-ui"
            variant="section"
            rounding="sm"
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
            color="danger"
            rounding="sm"
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
            color="muted"
            orientation="reverse"
            icon={SvgOnyxLogo}
            title={markdown(
              `[Onyx ${
                settings.version ?? "dev"
              }](https://docs.onyx.app/changelog)`
            )}
          />
        </div>,
      ]}
    </PopoverMenu>
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
  const { vectorDbEnabled } = useSettings();
  const { undismissedCount, refresh: refreshNotificationSummary } =
    useNotificationSummary();
  const userDisplayName = getUserDisplayName(user);

  const handlePopoverOpen = (state: boolean) => {
    if (state) {
      // Prefetch user settings data when popover opens for instant modal display
      preload("/api/user/pats", errorHandlingFetcher);
      preload("/api/federated/oauth-status", errorHandlingFetcher);
      if (vectorDbEnabled) {
        preload("/api/manage/connector-status", errorHandlingFetcher);
      }
      preload("/api/llm/provider", errorHandlingFetcher);
      void refreshNotificationSummary();
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
            icon={(props) => (
              <div className="w-[16px] flex flex-col justify-center items-center">
                <UserAvatar user={user} {...props} size={props.size} />
              </div>
            )}
            rightChildren={
              undismissedCount ? (
                <Section padding={0.5}>
                  <SvgNotificationBubble count={undismissedCount} />
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
        width={popupState === "Notifications" ? "2xl" : "lg"}
      >
        {popupState === "Settings" && (
          <SettingsPopover
            onUserSettingsClick={() => {
              setPopupState(undefined);
            }}
            onOpenNotifications={() => setPopupState("Notifications")}
            undismissedCount={undismissedCount}
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
