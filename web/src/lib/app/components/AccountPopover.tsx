"use client";

import { useNavigation, usePathname, useSearchParams } from "@opal/navigation";
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
  Button,
  Dropdown,
  LineItemButton,
  SidebarTab,
  useDropdownViews,
  type DropdownMenuItem,
  type DropdownView,
} from "@opal/components";
import NotificationsPopover from "@/lib/app/components/NotificationsPopover";
import {
  SvgBell,
  SvgChevronLeft,
  SvgExternalLink,
  SvgHelpCircle,
  SvgInfo,
  SvgLogOut,
  SvgSliders,
  SvgUser,
  SvgNotificationBubble,
} from "@opal/icons";
import { ContentAction, Section, toast, useSidebarFolded } from "@opal/layouts";
import { useAppPosition } from "@/lib/navigation/hooks";
import useScreenSize from "@/hooks/useScreenSize";
import { useSettings } from "@/lib/settings/hooks";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { useNotificationSummary } from "@/hooks/useNotifications";
import { SidebarLoader } from "@opal/loaders";
import { useTranslations } from "next-intl";
import { AboutDetails } from "@/lib/app/components/AboutDetails";

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
  const navigation = useNavigation();
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const currentUrl = query ? `${pathname}?${query}` : pathname;
  const isAnonymousUser =
    user?.is_anonymous_user || checkUserIsNoAuthUser(user?.id ?? "");
  const showLogout = user && !isAnonymousUser && !LOGOUT_DISABLED;
  const showLogin = isAnonymousUser;
  const userRowRef = useRef<HTMLDivElement>(null);

  const handleLogin = () => {
    navigation.go(loginPath({ next: currentUrl }));
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
        navigation.go(
          loginPath({ next: currentUrl, autoRedirectToSso: false })
        );
      })

      .catch(() => {
        toast.error(logoutFailedMessage);
      });
  };

  return [
    {
      kind: "custom",
      id: "user-email",
      keepOpen: true,
      // ArrowRight moves focus to the About button; Enter then presses it.
      onSecondary: () =>
        userRowRef.current?.querySelector<HTMLElement>("button")?.focus(),
      render: ({ props }) => (
        <div {...props} ref={userRowRef}>
          <ContentAction
            font="main-ui-action"
            title={
              userResolution === "unavailable"
                ? t("profileUnavailable.title")
                : getUserEmail(user)
            }
            // 4px around the 28px button: concentric in the 36px row.
            rightChildren={
              <Section width="fit" height="fit" padding={1}>
                <AboutButton />
              </Section>
            }
            center
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
              font="main-ui-action"
              presentational
              selectVariant="select-heavy"
              interaction={highlighted ? "hover" : "rest"}
              rounding={2}
              icon={SvgBell}
              title={t("notifications.label")}
              rightChildren={
                undismissedCount ? (
                  <Section width="fit" height="fit" padding={1}>
                    <SvgNotificationBubble count={undismissedCount} />
                  </Section>
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
      ],
    },
    ...(showLogin || showLogout
      ? [
          {
            kind: "group" as const,
            items: [
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
        ]
      : []),
  ];
}

/** Opens the about page, beside the user's email. */
function AboutButton() {
  const t = useTranslations("accountPopover");
  const views = useDropdownViews();
  return (
    <Button
      icon={SvgInfo}
      prominence="tertiary"
      size="md"
      tooltip={t("about.label")}
      aria-label={t("about.label")}
      onClick={() => views.push("about")}
    />
  );
}

/** The about page: a back row, then the build's details. */
function useAboutView(): DropdownView {
  const t = useTranslations("accountPopover");
  const detailsRef = useRef<HTMLDivElement>(null);
  // ArrowRight on the details row moves focus to its first link; Tab then
  // walks the rest, as on the notifications page.
  const focusDetails = () =>
    detailsRef.current?.querySelector<HTMLElement>("a")?.focus();
  return {
    // Wider than the menu, so long values (a URL, a ref) fit on one line.
    width: 80,
    items: [
      {
        kind: "action",
        id: "about-back",
        icon: SvgChevronLeft,
        title: t("about.label"),
        onSelect: (views) => views.pop(),
      },
      {
        kind: "custom",
        id: "about-details",
        keepOpen: true,
        onSecondary: focusDetails,
        render: ({ props }) => (
          <div {...props} ref={detailsRef}>
            <AboutDetails />
          </div>
        ),
      },
    ],
  };
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
  const aboutView = useAboutView();
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
    return <SidebarLoader width="full" folded={folded} />;
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
        views={{ notifications: notificationsView, about: aboutView }}
      />
    </Dropdown>
  );
}
