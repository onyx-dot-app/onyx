"use client";

import { PageLoader } from "@opal/loaders";
import { usePathname } from "@opal/navigation";
import { useAppPosition } from "@/lib/navigation/hooks";
import AgentsCatalogLoading from "@/views/AgentsCatalogPage/loading";
import AgentEditorLoading from "@/views/AgentEditorPage/loading";
import PluginsLoading from "@/views/PluginsPage/loading";

/**
 * The loading screen of the URL's page: `AppChrome`'s `PendingRoute` loader,
 * and /app's `loading.tsx`. `go` writes the URL first, so it names the page
 * being loaded. A view of /app (a chat, an agent, a project, a new session) is
 * blank until it mounts and shows its own state. Other pages without a loader
 * of their own get the page loader.
 */
export function AppChromeLoader() {
  const position = useAppPosition();
  const pathname = usePathname();
  if (pathname === "/app/agents") return <AgentsCatalogLoading />;
  if (pathname.startsWith("/app/agents/")) return <AgentEditorLoading />;
  if (pathname === "/app/plugins") return <PluginsLoading />;
  if (
    position.isChat() ||
    position.isNewSession() ||
    position.isAgent() ||
    position.isProject()
  ) {
    return <div />;
  }
  return <PageLoader />;
}
