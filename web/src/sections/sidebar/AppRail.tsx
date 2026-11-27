"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import { SidebarTab } from "@opal/components";
import { SidebarLayouts } from "@opal/layouts";
import { useNavigation, usePathname } from "@opal/navigation";
import {
  SvgBubbleText,
  SvgOnyxOctagon,
  SvgSettings,
  SvgSliders,
} from "@opal/icons";
import { AccountPopover } from "@/lib/app/components";
import { useAppPosition } from "@/lib/navigation/hooks";
import { getFirstPermittedAdminRoute } from "@/lib/permissions/utils";
import { CUSTOMIZE_PATH } from "@/lib/customize/paths";
import { sidebarWindow } from "@/lib/sidebar/utils";
import { useUser } from "@/providers/UserProvider";
import { useChatShortcutActions } from "@/lib/shortcuts/hooks";

interface AppRailProps {
  /** Opens the Craft intro from the account menu, where Craft is enabled. */
  onShowBuildIntro?: () => void;
}

/** The app's window rail: Chat, Agents, Customize, then admin and account. */
export default function AppRail({ onShowBuildIntro }: AppRailProps) {
  const t = useTranslations("sidebar");
  const navigation = useNavigation();
  const appPosition = useAppPosition();
  const activeWindow = sidebarWindow(usePathname());
  const { hasAdminAccess, adminCapabilities } = useUser();
  const newSession = appPosition.linkToNewSession();
  const { resetNewSession } = useChatShortcutActions();

  return (
    <SidebarLayouts.Rail
      footer={
        <>
          {hasAdminAccess && (
            <div data-testid="AppRail/admin">
              <SidebarTab
                icon={SvgSettings}
                {...navigation.linkTo(
                  // SAFETY: the first permitted admin route is a page of this app.
                  getFirstPermittedAdminRoute(adminCapabilities) as Route,
                  { scroll: false }
                )}
                selected={activeWindow === "admin"}
              >
                {t("appSidebar.adminPanel.label")}
              </SidebarTab>
            </div>
          )}
          <AccountPopover onShowBuildIntro={onShowBuildIntro} />
        </>
      }
    >
      <div data-testid="AppRail/chat">
        <SidebarTab
          icon={SvgBubbleText}
          href={newSession.href}
          onClick={(event) => {
            const handledBefore = event.defaultPrevented;
            newSession.onClick(event);
            if (!handledBefore && event.defaultPrevented) resetNewSession();
          }}
          selected={activeWindow === "chat"}
        >
          {t("appRail.chat.label")}
        </SidebarTab>
      </div>
      <div data-testid="AppRail/agents">
        <SidebarTab
          icon={SvgOnyxOctagon}
          {...navigation.linkTo("/app/agents", { scroll: false })}
          selected={activeWindow === "agents"}
        >
          {t("appRail.agents.label")}
        </SidebarTab>
      </div>
      <div data-testid="AppRail/customize">
        <SidebarTab
          icon={SvgSliders}
          {...navigation.linkTo(CUSTOMIZE_PATH, { scroll: false })}
          selected={activeWindow === "customize"}
        >
          {t("appSidebar.customize.label")}
        </SidebarTab>
      </div>
    </SidebarLayouts.Rail>
  );
}
