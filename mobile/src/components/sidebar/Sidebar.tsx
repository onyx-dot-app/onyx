import { Image } from "expo-image";
import { router } from "expo-router";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Text } from "@/components/opal";
import { useToken } from "@/theme/ThemeProvider";
import { useDrawer } from "@/components/drawer/DrawerProvider";
import { EditBigIcon, SidebarIcon } from "@/components/ui/icons";
import { SidebarSection } from "./SidebarSection";
import { SidebarRow } from "./SidebarRow";
import { useChatSessions } from "@/query/sessions";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useStartNewChat } from "@/chat/useStartNewChat";

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
  const collapseColor = useToken("text-03");

  const { data: sessions, isLoading } = useChatSessions();
  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);
  const startNewChat = useStartNewChat();
  const newChatColor = useToken("text-04");

  async function handleNewChat() {
    close();
    await startNewChat();
    router.navigate("/(app)/(chat)" as never);
  }

  // Most-recent first. We do NOT filter out un-named sessions: web shows them with
  // a "New Chat" fallback (the backend titles a session shortly after its first
  // message — see useChatSessionLifecycle.autoNameSession). With lazy creation,
  // empty/untitled sessions aren't spawned on the "New Chat" tap anyway.
  const recents = (sessions ?? [])
    .slice()
    .sort(
      (a, b) =>
        new Date(b.time_created).getTime() - new Date(a.time_created).getTime(),
    );

  function openSession(id: string) {
    // Open in the single chat screen (it loads + hydrates this session's history)
    // rather than pushing a separate [sessionId] route. `navigate` (not `push`)
    // avoids stacking chat screens.
    setCurrentSession(id);
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
          <Image
            source={require("../../../assets/images/icon.png")}
            style={{ width: 30, height: 30, borderRadius: 8 }}
            contentFit="cover"
          />
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
          <SidebarIcon size={20} color={collapseColor} />
        </Pressable>
      </View>

      {/* New Chat (web: SidebarTab "New Session", above Recents) */}
      <Pressable
        onPress={handleNewChat}
        accessibilityRole="button"
        accessibilityLabel="New chat"
        className="mx-2 mb-1 h-10 flex-row items-center gap-2 rounded-[8px] px-2 active:bg-background-tint-03"
      >
        <EditBigIcon size={18} color={newChatColor} />
        <Text font="main-ui-body" color="text-04">
          New Chat
        </Text>
      </Pressable>

      {/* Body — Recents. 8px side padding (web `px-2`) on a real wrapper View so it
          reliably applies (ScrollView contentContainerStyle padding was dropped). */}
      <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
        <View style={{ paddingTop: 4, paddingBottom: 16 }}>
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
                  label={(s.name ?? "").trim() || "New Chat"}
                  selected={s.id === currentSessionId}
                  onPress={() => openSession(s.id)}
                />
              ))
            )}
          </SidebarSection>
        </View>
      </ScrollView>
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
