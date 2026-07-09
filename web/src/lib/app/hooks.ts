"use client";

import { useLayoutEffect } from "react";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import useAppFocus from "@/hooks/useAppFocus";
import useChatSessions from "@/hooks/useChatSessions";
import { usePathname } from "next/navigation";
import { getAppLogo } from "@/lib/app/utils";
import type { IconFunctionComponent } from "@opal/types";

export function useAppLogo(folded: boolean): IconFunctionComponent {
  const { logoUrl } = useSettings();
  return getAppLogo(logoUrl, folded);
}

export function useCustomFooterContent(): string {
  const settings = useSettings();
  return (
    settings.enterprise?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}

export function useAppDocumentTitle(): void {
  const { appName } = useSettings();
  const appFocus = useAppFocus();
  const { currentChatSession } = useChatSessions();

  useLayoutEffect(() => {
    const appendChatName =
      (appFocus.isChat() || appFocus.isSharedChat()) && currentChatSession;
    document.title = appendChatName
      ? `${currentChatSession.name} — ${appName}`
      : appName;
  }, [currentChatSession?.name, appName, appFocus]);
}

export function useAdminDocumentTitle(): void {
  const { appName } = useSettings();
  const pathname = usePathname();

  useLayoutEffect(() => {
    document.title = `Admin — ${appName}`;
  }, [pathname, appName]);
}

export function useAuthDocumentTitle(): void {
  const { appName } = useSettings();

  useLayoutEffect(() => {
    document.title = appName;
  }, [appName]);
}
