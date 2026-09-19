import { router, useGlobalSearchParams, useSegments } from "expo-router";

import { Icon } from "@/components/ui/icon";
import { SidebarLayouts, SidebarTab, useSidebar } from "@/components/sidebar";
import SvgOnyxLogo from "@/icons/onyx-logo";
import SvgPlus from "@/icons/plus";
import { useLogout } from "@/api/auth/useLogout";
import { useChatSessions } from "@/api/chat/sessions";
import { AgentSidebarSection } from "@/components/chat/AgentSidebarSection";
import { useProjects } from "@/api/chat/projects";
import { ChatSessionList } from "@/components/chat/ChatSessionList";
import { ProjectList } from "@/components/chat/ProjectList";

// Mounted in (app)/_layout so the overlay spans every authed screen.
export function AppSidebar() {
  const { setFolded } = useSidebar();
  const logout = useLogout();

  // `id` is the param for BOTH /chat/[id] and /projects/[id] — the active
  // segment tells them apart.
  // widen — expo-router's typed-routes union narrows `.includes()` arg to `never`
  const segments: readonly string[] = useSegments();
  const params = useGlobalSearchParams<{ id?: string }>();
  const rawId = typeof params.id === "string" ? params.id : null;
  const inChat = segments.includes("chat");
  const inProject = segments.includes("projects");
  const currentSessionId = inChat ? rawId : null;
  const currentProjectId = inProject && rawId != null ? Number(rawId) : null;
  const onNewChat = !inChat && !inProject;

  const {
    sessions,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useChatSessions();
  const { projects, isLoading: isLoadingProjects } = useProjects();

  function openNewChat() {
    setFolded(true);
    router.navigate("/");
  }

  function openSession(sessionId: string) {
    setFolded(true);
    router.navigate({ pathname: "/chat/[id]", params: { id: sessionId } });
  }

  function openProject(projectId: number) {
    setFolded(true);
    router.navigate({
      pathname: "/projects/[id]",
      params: { id: String(projectId) },
    });
  }

  return (
    <SidebarLayouts.Root foldable>
      <SidebarLayouts.Header
        logo={() => (
          <Icon as={SvgOnyxLogo} size={24} className="px-1 text-text-05" />
        )}
      />

      <SidebarLayouts.Body scrollKey="chats">
        <SidebarTab icon={SvgPlus} selected={onNewChat} onPress={openNewChat}>
          New chat
        </SidebarTab>

        <AgentSidebarSection />

        <SidebarLayouts.Section title="Projects">
          <ProjectList
            projects={projects}
            currentProjectId={currentProjectId}
            isLoading={isLoadingProjects}
            onSelect={openProject}
          />
        </SidebarLayouts.Section>

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
