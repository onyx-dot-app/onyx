import { router, useGlobalSearchParams } from "expo-router";

import { Icon } from "@/components/ui/icon";
import { SidebarLayouts, SidebarTab, useSidebar } from "@/components/sidebar";
import SvgOnyxLogo from "@/icons/onyx-logo";
import SvgPlus from "@/icons/plus";
import { useLogout } from "@/api/auth/useLogout";
import { useChatSessions } from "@/api/chat/sessions";
import { AgentSidebarSection } from "@/components/chat/AgentSidebarSection";
import { ChatSessionList } from "@/components/chat/ChatSessionList";

// Mobile analog of web's `AppSidebar`: New chat + flat "Recents" + footer.
// Mounted in (app)/_layout so the overlay spans every authed screen. Projects: PR 6.
export function AppSidebar() {
  const { setFolded } = useSidebar();
  const logout = useLogout();
  const params = useGlobalSearchParams<{ id?: string }>();
  const currentSessionId = typeof params.id === "string" ? params.id : null;

  const {
    sessions,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useChatSessions();

  function openNewChat() {
    setFolded(true);
    router.navigate("/");
  }

  function openSession(sessionId: string) {
    setFolded(true);
    router.navigate({ pathname: "/chat/[id]", params: { id: sessionId } });
  }

  return (
    <SidebarLayouts.Root foldable>
      <SidebarLayouts.Header
        logo={() => (
          <Icon as={SvgOnyxLogo} size={24} className="px-1 text-text-05" />
        )}
      />

      <SidebarLayouts.Body scrollKey="chats">
        <SidebarTab
          icon={SvgPlus}
          selected={currentSessionId === null}
          onPress={openNewChat}
        >
          New chat
        </SidebarTab>

        <AgentSidebarSection />

        <SidebarLayouts.Section title="Recents">
          <ChatSessionList
            sessions={sessions}
            currentSessionId={currentSessionId}
            isLoading={isLoading}
            hasMore={hasNextPage}
            isLoadingMore={isFetchingNextPage}
            onSelect={openSession}
            onLoadMore={() => fetchNextPage()}
          />
        </SidebarLayouts.Section>
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        <SidebarTab
          variant="sidebar-light"
          disabled={logout.isPending}
          onPress={() => logout.mutate()}
        >
          {logout.isPending ? "Logging out…" : "Log out"}
        </SidebarTab>
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
