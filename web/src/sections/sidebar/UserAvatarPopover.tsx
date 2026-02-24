"use client";

import { useState } from "react";
import { ANONYMOUS_USER_NAME, LOGOUT_DISABLED } from "@/lib/constants";
import { Notification } from "@/interfaces/settings";
import useSWR, { preload } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
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
import { toast } from "@/hooks/useToast";
import useAppFocus from "@/hooks/useAppFocus";

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
  onOpenNotifications: () => void;
}

function SettingsPopover({
  onUserSettingsClick,
  onOpenNotifications,
}: SettingsPopoverProps) {
  const { user } = useUser();
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
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
            <LineItem icon={SvgUser} onClick={onUserSettingsClick}>
              User Settings
            </LineItem>
          </div>,
          <LineItem
            key="notifications"
            icon={SvgBell}
            onClick={onOpenNotifications}
          >
            {`Notifications${
              undismissedCount > 0 ? ` (${undismissedCount})` : ""
            }`}
          </LineItem>,
          <LineItem
            key="help-faq"
            icon={SvgExternalLink}
            onClick={() =>
              window.open(
                "https://docs.onyx.app",
                "_blank",
                "noopener,noreferrer"
              )
            }
          >
            Help & FAQ
          </LineItem>,
          null,
          showLogin && (
            <LineItem key="log-in" icon={SvgUser} onClick={handleLogin}>
              Log in
            </LineItem>
          ),
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
  onShowBuildIntro?: () => void;
}

export default function UserAvatarPopover({
  folded,
  onShowBuildIntro,
}: SettingsProps) {
  const [popupState, setPopupState] = useState<
    "Settings" | "Notifications" | undefined
  >(undefined);
  const { user } = useUser();
  const router = useRouter();
  const appFocus = useAppFocus();

  // Fetch notifications for display
  // The GET endpoint also triggers a refresh if release notes are stale
  const { data: notifications } = useSWR<Notification[]>(
    "/api/notifications",
    errorHandlingFetcher
  );

  const displayName = getDisplayName(user?.email, user?.personalization?.name);
  const undismissedCount =
    notifications?.filter((n) => !n.dismissed).length ?? 0;
  const hasNotifications = undismissedCount > 0;

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
            transient={!!popupState || appFocus.isUserSettings()}
            folded={folded}
          >
            {displayName}
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
              router.push("/app/settings");
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
