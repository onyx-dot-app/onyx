"use client";

import { useRef, useState } from "react";
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
import { loginPath } from "@/lib/auth/paths";
import {
  Dropdown,
  LineItemButton,
  SidebarTab,
  useDropdownViews,
  type DropdownMenuItem,
  type DropdownView,
} from "@opal/components";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import { Content, toast, useSidebarFolded } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { useAppPosition } from "@/lib/position/hooks";
import useScreenSize from "@/hooks/useScreenSize";
import { useSettings } from "@/lib/settings/hooks";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import SidebarTabSkeleton from "@/refresh-components/skeletons/SidebarTabSkeleton";
import { useNotificationSummary } from "@/hooks/useNotifications";
import { SvgOnyxLogo } from "@opal/logos";
import { markdown } from "@opal/utils";
import { useTranslations } from "next-intl";

interface SettingsItemsProps {
  undismissedCount: number;
}

/** The account menu's rows. The notifications row leads to its page. */
function useSettingsItems({
  undismissedCount,
}: SettingsItemsProps): DropdownMenuItem[] {
  const t = useTranslations("accountPopover");
  const { user, userResolution } = useUser();
  const settings = useSettings();
  const enterpriseSettings = settings.enterprise;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isAnonymousUser =
    user?.is_anonymous_user || checkUserIsNoAuthUser(user?.id ?? "");
  const showLogout = user && !isAnonymousUser && !LOGOUT_DISABLED;
  const showLogin = isAnonymousUser;

  const query = searchParams?.toString();
  const currentUrl = query ? `${pathname}?${query}` : pathname;

  const handleLogin = () => {
    router.push(loginPath({ next: currentUrl }));
  };

  const logoutFailedMessage = t("logoutFailed.message");

  const handleLogout = () => {
    logout()
      .then((response) => {
        if (!response?.ok) {
          alert(logoutFailedMessage);
          return;
        }

        // Held on the login button: with SSO as the only way in, an auto
        // start would sign the user straight back in through the IdP session.
        router.push(loginPath({ next: currentUrl, autoRedirectToSso: false }));
      })

      .catch(() => {
        toast.error(logoutFailedMessage);
      });
  };

  return [
    {
      kind: "custom",
      id: "user-email",
      disabled: true,
      render: ({ props }) => (
        <div {...props} className="p-2">
          <Content
            sizePreset="main-ui"
            title={
              userResolution === "unavailable"
                ? t("profileUnavailable.title")
                : getUserEmail(user)
            }
          />
        </div>
      ),
    },
    {
      kind: "group",
      items: [
        {
          kind: "action",
          id: "user-settings",
          icon: SvgSliders,
          title: t("settings.label"),
          href: "/app/settings",
        },
        {
          kind: "custom",
          id: "notifications",
          keywords: [t("notifications.label")],
          onActivate: (views) => views.push("notifications"),
          render: ({ highlighted, props }) => (
            <LineItemButton
              presentational
              selectVariant="select-heavy"
              interaction={highlighted ? "hover" : "rest"}
              sizePreset="main-ui"
              variant="section"
              rounding={2}
              icon={SvgBell}
              title={t("notifications.label")}
              rightChildren={
                undismissedCount ? (
                  <SvgNotificationBubble count={undismissedCount} />
                ) : undefined
              }
              {...props}
            />
          ),
        },
        {
          kind: "action",
          id: "help-faq",
          icon: SvgHelpCircle,
          title: t("helpFaq.label"),
          href: "https://docs.onyx.app",
          target: "_blank",
        },
        ...(enterpriseSettings?.custom_help_link_url
          ? [
              {
                kind: "action" as const,
                id: "custom-help-link",
                icon: SvgExternalLink,
                title:
                  enterpriseSettings.custom_help_link_label ||
                  enterpriseSettings.custom_help_link_url,
                href: enterpriseSettings.custom_help_link_url,
                target: "_blank",
              },
            ]
          : []),
        ...(showLogin
          ? [
              {
                kind: "action" as const,
                id: "log-in",
                icon: SvgUser,
                title: t("logIn.label"),
                onSelect: handleLogin,
              },
            ]
          : []),
        ...(showLogout
          ? [
              {
                kind: "action" as const,
                id: "log-out",
                icon: SvgLogOut,
                danger: true,
                title: t("signOut.label"),
                onSelect: handleLogout,
              },
            ]
          : []),
      ],
    },
    {
      kind: "group",
      items: [
        {
          kind: "custom",
          id: "version",
          disabled: true,
          render: ({ props }) => (
            <div {...props} className="p-2">
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
            </div>
          ),
        },
      ],
    },
  ];
}

interface NotificationsPageProps {
  onShowBuildIntro?: () => void;
}

/** The notifications page, one row holding the panel; back pops, a pick closes. */
function NotificationsPage({ onShowBuildIntro }: NotificationsPageProps) {
  const views = useDropdownViews();
  return (
    <NotificationsPopover
      onClose={() => views.pop()}
      onNavigate={() => views.close()}
      onShowBuildIntro={onShowBuildIntro}
    />
  );
}

export interface SettingsProps {
  onShowBuildIntro?: () => void;
}

export default function AccountPopover({ onShowBuildIntro }: SettingsProps) {
  const t = useTranslations("accountPopover");
  const folded = useSidebarFolded();
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, userResolution } = useUser();
  const appPosition = useAppPosition();
  const { isMobile } = useScreenSize();
  const { vectorDbEnabled } = useSettings();
  const notificationsPageRef = useRef<HTMLDivElement>(null);
  const { undismissedCount, refresh: refreshNotificationSummary } =
    useNotificationSummary();
  const userDisplayName =
    userResolution === "unavailable"
      ? t("accountFallback.label")
      : getUserDisplayName(user);

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
    }
    setMenuOpen(state);
  };
  const items = useSettingsItems({ undismissedCount });
  // ArrowRight on the page row moves focus into it; Tab then walks its
  // controls. Not on activation: a click on a control inside the page
  // bubbles to the row, and must not pull focus off that control.
  const focusNotificationsPage = () =>
    notificationsPageRef.current
      ?.querySelector<HTMLElement>("button, a, [tabindex='0']")
      ?.focus();
  const notificationsView: DropdownView = {
    width: 90,
    items: [
      {
        kind: "custom",
        id: "notifications-page",
        keepOpen: true,
        onSecondary: focusNotificationsPage,
        render: ({ props }) => (
          <div {...props} ref={notificationsPageRef}>
            <NotificationsPage onShowBuildIntro={onShowBuildIntro} />
          </div>
        ),
      },
    ],
  };
  if (userResolution === "loading") {
    return <SidebarTabSkeleton folded={folded} />;
  }

  return (
    <Dropdown
      width={60}
      // On a phone the sidebar is the whole screen: the menu opens above
      // the tab rather than beside it.
      side={isMobile ? "top" : "right"}
      align={isMobile ? "start" : "end"}
      tabKey="walk"
      open={menuOpen}
      onOpenChange={handlePopoverOpen}
    >
      <Dropdown.Trigger asChild>
        <div id="onyx-user-dropdown">
          <SidebarTab
            icon={(props) => (
              <div className="w-[16px] flex flex-col justify-center items-center">
                <UserAvatar user={user} {...props} size={props.size} />
              </div>
            )}
            rightChildren={
              undismissedCount ? (
                <Section padding={2}>
                  <SvgNotificationBubble count={undismissedCount} />
                </Section>
              ) : undefined
            }
            type="button"
            selected={menuOpen || appPosition.isUserSettings()}
          >
            {userDisplayName}
          </SidebarTab>
        </div>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={userDisplayName}
        // The notifications page scrolls itself at its own height; the
        // list must not add a second cap around it.
        maxHeight="none"
        items={items}
        views={{ notifications: notificationsView }}
      />
    </Dropdown>
  );
}
