"use client";

import { useLayoutEffect } from "react";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import useAppFocus from "@/hooks/useAppFocus";
import useChatSessions from "@/hooks/useChatSessions";

export function useCustomFooterContent(): string {
  const settings = useSettings();
  return (
    settings.enterprise?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}

export function useAppDocumentTitle(): void {
  const appFocus = useAppFocus();
  const { appName } = useSettings();
  const { currentChatSession } = useChatSessions();
  useLayoutEffect(() => {
    const appendChatNameToDocumentTitle =
      (appFocus.isChat() || appFocus.isSharedChat()) &&
      currentChatSession?.name;
    document.title = appendChatNameToDocumentTitle
      ? `${currentChatSession.name} — ${appName}`
      : appName;
  }, [currentChatSession?.name, appName, appFocus]);
}

export function useAdminDocumentTitle(): void {
  const pathname = usePathname();
  const { appName } = useSettings();
  useLayoutEffect(() => {
    document.title = `Admin — ${appName}`;
  }, [pathname, appName]);
}
