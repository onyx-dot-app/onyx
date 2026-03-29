"use client";

// "AppFocus" is the current part of the main application which is active / focused on.
// Namely, if the URL is pointing towards a "chat", then a `{ type: "chat", id: "..." }` is returned.
//
// This is useful in determining what `SidebarTab` should be active, for example.

import { useMemo } from "react";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { usePathname, useSearchParams } from "next/navigation";

export type AppFocusType =
  | { type: "agent" | "project" | "chat"; id: string }
  | "new-session"
  | "more-agents"
  | "user-settings"
  | "shared-chat"
  | "company-files";

export class AppFocus {
  constructor(public value: AppFocusType) {}

  isAgent(): boolean {
    return typeof this.value === "object" && this.value.type === "agent";
  }

  isProject(): boolean {
    return typeof this.value === "object" && this.value.type === "project";
  }

  isChat(): boolean {
    return typeof this.value === "object" && this.value.type === "chat";
  }

  isSharedChat(): boolean {
    return this.value === "shared-chat";
  }

  isNewSession(): boolean {
    return this.value === "new-session";
  }

  isMoreAgents(): boolean {
    return this.value === "more-agents";
  }

  isUserSettings(): boolean {
    return this.value === "user-settings";
  }

  isCompanyFiles(): boolean {
    return this.value === "company-files";
  }

  getId(): string | null {
    return typeof this.value === "object" ? this.value.id : null;
  }

  getType():
    | "agent"
    | "project"
    | "chat"
    | "shared-chat"
    | "new-session"
    | "more-agents"
    | "user-settings"
    | "company-files" {
    return typeof this.value === "object" ? this.value.type : this.value;
  }
}

export default function useAppFocus(): AppFocus {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const agentId = searchParams.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const projectId = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);

  // Memoize on the values that determine which AppFocus is constructed.
  // AppFocus is immutable, so same inputs → same instance.
  return useMemo(() => {
    if (pathname.startsWith("/app/shared/")) {
      return new AppFocus("shared-chat");
    }
    if (pathname.startsWith("/app/settings")) {
      return new AppFocus("user-settings");
    }
    if (pathname.startsWith("/app/company-files")) {
      return new AppFocus("company-files");
    }
    if (pathname.startsWith("/app/agents")) {
      return new AppFocus("more-agents");
    }
    if (chatId) return new AppFocus({ type: "chat", id: chatId });
    if (agentId) return new AppFocus({ type: "agent", id: agentId });
    if (projectId) return new AppFocus({ type: "project", id: projectId });
    return new AppFocus("new-session");
  }, [pathname, chatId, agentId, projectId]);
}
