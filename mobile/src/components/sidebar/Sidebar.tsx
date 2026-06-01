import { useMemo, useState } from "react";
import { router } from "expo-router";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Text } from "@/components/opal";
import { useToken } from "@/theme/ThemeProvider";
import { useAuth } from "@/auth";
import { useDrawer } from "@/components/drawer/DrawerProvider";
import { OnyxLogo } from "@/components/ui/logos";
import { SvgEditBig, SvgFolderPlus, SvgLogOut } from "@/components/icons";
import { SvgSidebar } from "@/components/icons/SvgSidebar";
import { SidebarSection } from "./SidebarSection";
import { SidebarRow } from "./SidebarRow";
import { ProjectFolderRow } from "./ProjectFolderRow";
import { CreateProjectModal } from "@/components/projects/CreateProjectModal";
import { useChatSessions } from "@/query/sessions";
import { useProjects } from "@/query/projects";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useStartNewChat } from "@/chat/useStartNewChat";
import { useOpenExistingChat } from "@/chat/useOpenExistingChat";
import { chatDisplayName } from "@/lib/chatLabels";

// Drawer sidebar. Surface matches the web chat sidebar exactly (bg-background-tint-02,
// generated from the web Opal palette).
//
// Phase 03 = header (logo + workspace name + collapse).
// Phase 04 = live "Recents" list (chat sessions, tap to open).
//
// Horizontal rhythm mirrors the web: the body has 8px side padding (web `px-2`),
// and the section header + rows add their own 8px, so text sits at 16px and the row
// highlight is inset 8px from the drawer edge.
export function Sidebar() {
  const insets = useSafeAreaInsets();
  const { close } = useDrawer();
  const logoColor = useToken("theme-primary-05");

  const { data: sessions, isLoading } = useChatSessions();
  const { data: projects } = useProjects();
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const startNewChat = useStartNewChat();
  const openExistingChat = useOpenExistingChat();
  const iconColor = useToken("text-04");
  const { signOut } = useAuth();
  const [createProjectOpen, setCreateProjectOpen] = useState(false);

  // Sign out, then close the drawer. The (app) auth guard redirects to the login
  // screen reactively once status flips to "signedOut" — no manual nav needed.
  async function handleLogout() {
    close();
    await signOut();
  }

  async function handleNewChat() {
    close();
    await startNewChat();
    router.navigate("/(app)/(chat)" as never);
  }

  // Most-recent first. We do NOT filter out un-named sessions: web shows them with
  // a "New Chat" fallback (the backend titles a session shortly after its first
  // message — see useChatSessionLifecycle.autoNameSession). With lazy creation,
  // empty/untitled sessions aren't spawned on the "New Chat" tap anyway.
  const recents = useMemo(
    () =>
      (sessions ?? [])
        .slice()
        .sort(
          (a, b) =>
            new Date(b.time_created).getTime() -
            new Date(a.time_created).getTime(),
        ),
    [sessions],
  );

  function openSession(id: string) {
    // Clears any lingering project target + makes the session current (hydrates its
    // history). Open in the single chat screen rather than pushing a separate
    // [sessionId] route. `navigate` (not `push`) avoids stacking chat screens.
    openExistingChat(id);
    close();
    router.navigate("/(app)/(chat)" as never);
  }

  return (
    <View
      className="flex-1 bg-background-tint-02"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      {/* Header — logo + workspace name + collapse toggle (web: SidebarWrapper) */}
      <View
        className="flex-row items-center justify-between pb-2 pt-3"
        style={{ paddingHorizontal: 12 }}
      >
        <View className="flex-1 flex-row items-center gap-2">
          <OnyxLogo size={28} color={logoColor} />
          <View className="flex-1">
            {/* TODO: bind real workspace/tenant name when available */}
            <Text font="main-ui-action" color="text-05">
              Onyx
            </Text>
            <Text font="secondary-body" color="text-03">
              Powered by Onyx
            </Text>
          </View>
        </View>

        <Pressable
          onPress={close}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="Close sidebar"
          style={{ padding: 6, borderRadius: 8 }}
        >
          <SvgSidebar size={20} color="text-03" />
        </Pressable>
      </View>

      {/* New Chat (web: SidebarTab "New Session", above Recents) */}
      <Pressable
        onPress={handleNewChat}
        accessibilityRole="button"
        accessibilityLabel="New chat"
        className="mx-2 mb-1 h-10 flex-row items-center gap-2 rounded-[8px] px-2 active:bg-background-tint-03"
      >
        <SvgEditBig size={18} color={iconColor} />
        <Text font="main-ui-body" color="text-04">
          New Chat
        </Text>
      </Pressable>

      {/* Body — Recents. 8px side padding (web `px-2`) on a real wrapper View so it
          reliably applies (ScrollView contentContainerStyle padding was dropped). */}
      <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
        <View style={{ paddingTop: 4, paddingBottom: 16 }}>
          {/* Projects (web: AppSidebar Projects section above the chat history) */}
          <SidebarSection title="Projects">
            <Pressable
              onPress={() => {
                // Close the drawer so the modal (and the subsequent project
                // navigation) isn't left behind the open sidebar.
                close();
                setCreateProjectOpen(true);
              }}
              accessibilityRole="button"
              accessibilityLabel="New project"
              className="mx-2 mb-1 h-10 flex-row items-center gap-2 rounded-[8px] px-2 active:bg-background-tint-03"
            >
              <SvgFolderPlus size={18} color={iconColor} />
              <Text font="main-ui-body" color="text-04">
                New Project
              </Text>
            </Pressable>
            {(projects ?? []).map((project) => (
              <ProjectFolderRow key={project.id} project={project} />
            ))}
          </SidebarSection>

          <SidebarSection title="Recents">
            {isLoading ? (
              <RecentsSkeleton />
            ) : recents.length === 0 ? (
              <View className="pl-4 pr-2 py-2">
                <Text font="secondary-body" color="text-03">
                  Try sending a message! Your chat history will appear here.
                </Text>
              </View>
            ) : (
              recents.map((s) => (
                <SidebarRow
                  key={s.id}
                  label={chatDisplayName(s.name)}
                  selected={s.id === currentSessionId}
                  onPress={() => openSession(s.id)}
                />
              ))
            )}
          </SidebarSection>
        </View>
      </ScrollView>

      {/* Footer — Log out, pinned at the bottom of the sidebar. */}
      <View className="border-t border-border-01 px-2 pb-1 pt-2">
        <Pressable
          onPress={handleLogout}
          accessibilityRole="button"
          accessibilityLabel="Log out"
          className="h-10 flex-row items-center gap-2 rounded-[8px] px-2 active:bg-background-tint-03"
        >
          <SvgLogOut size={18} color={iconColor} />
          <Text font="main-ui-body" color="text-04">
            Log out
          </Text>
        </Pressable>
      </View>

      <CreateProjectModal
        visible={createProjectOpen}
        onClose={() => setCreateProjectOpen(false)}
      />
    </View>
  );
}

// Three muted placeholder rows while the session list loads (mirrors web skeletons).
function RecentsSkeleton() {
  const barColor = useToken("background-tint-03");
  const widths = ["80%", "60%", "70%"] as const;
  return (
    <View className="gap-3 pl-4 pr-2 py-2">
      {widths.map((w, i) => (
        <View
          key={i}
          style={{ width: w, height: 14, borderRadius: 7, backgroundColor: barColor }}
        />
      ))}
    </View>
  );
}
