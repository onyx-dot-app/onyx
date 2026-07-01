import { useLayoutEffect } from "react";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import type { AppFocus } from "@/hooks/useAppFocus";
import type { ChatSession } from "@/app/app/interfaces";

export function useCustomFooterContent(): string {
  const settings = useSettings();
  return (
    settings.enterprise?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}

export function useAppDocumentTitle(
  appFocus: AppFocus,
  currentChatSession: ChatSession | null,
  appName: string
): void {
  useLayoutEffect(() => {
    const appendChatName =
      (appFocus.isChat() || appFocus.isSharedChat()) && currentChatSession;
    document.title = appendChatName
      ? `${currentChatSession.name} — ${appName}`
      : appName;
  }, [currentChatSession?.name, appName, appFocus]);
}

export function useAdminDocumentTitle(pathname: string, appName: string): void {
  useLayoutEffect(() => {
    document.title = `Admin — ${appName}`;
  }, [pathname, appName]);
}

export function useAuthDocumentTitle(appName: string): void {
  useLayoutEffect(() => {
    document.title = appName;
  }, [appName]);
}
