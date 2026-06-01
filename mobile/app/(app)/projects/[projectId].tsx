import { useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgEditBig, SvgTrash } from "@/components/icons";
import { SvgMoreHorizontal } from "@/components/icons/SvgMoreHorizontal";
import { useToken } from "@/theme/ThemeProvider";
import { useProjects, useProjectDetails } from "@/query/projects";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useHydrateCurrentSession } from "@/chat/useHydrateCurrentSession";
import { useResetForcedToolsOnSessionChange } from "@/state/useForcedTools";
import { useStartProjectChat } from "@/chat/useStartProjectChat";
import { useOpenExistingChat } from "@/chat/useOpenExistingChat";
import { useConfirmDeleteProject } from "@/chat/confirmDeleteProject";
import { ChatThreadBody } from "@/components/chat/ChatThreadBody";
import { ScreenHeader } from "@/components/chat/ScreenHeader";
import { ProjectContextPanel } from "@/components/projects/ProjectContextPanel";
import { ProjectChatSessionList } from "@/components/projects/ProjectChatSessionList";
import { AddInstructionModal } from "@/components/projects/AddInstructionModal";

// Project screen. Mobile adaptation of web's `?projectId` landing view — and, like
// web, the SAME screen flips between the project view and the chat view:
//   • currentSessionId === null  → project draft: show the ProjectContextPanel
//     (name / instructions / files) + Recent Chats, with the real composer below.
//   • currentSessionId !== null  → a chat is active (first send created it, or an
//     existing project chat was opened): the project UI hides and the normal chat
//     thread takes over IN PLACE. The composer is rendered OUTSIDE the conditional
//     so its useSendMessage hook stays mounted across the flip (no navigation, no
//     stream abort) — exactly how the chat screen goes draft→real on first send.
export default function ProjectScreen() {
  const params = useLocalSearchParams<{ projectId: string }>();
  const projectId = Number.parseInt(String(params.projectId), 10);

  const iconColor = useToken("text-04");
  const dangerColor = useToken("action-text-danger-05");

  const { data: projects } = useProjects();
  const { data: details, isLoading: detailsLoading } = useProjectDetails(
    Number.isNaN(projectId) ? null : projectId,
  );
  const startProjectChat = useStartProjectChat();
  const openExistingChat = useOpenExistingChat();
  const confirmDeleteProject = useConfirmDeleteProject();

  const currentSessionId = useChatSessionStore((s) => s.currentSessionId);
  const { isLoading: hydrating, isError, retry } = useHydrateCurrentSession();
  useResetForcedToolsOnSessionChange();

  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const menuRef = useRef<PopoverTriggerRef>(null);

  if (Number.isNaN(projectId)) return null;

  const listProject = projects?.find((p) => p.id === projectId);
  const project = details?.project ?? listProject;
  const files = details?.files ?? [];
  const chats =
    details?.project?.chat_sessions ?? listProject?.chat_sessions ?? [];

  // A chat is active once a session is current (set by the first send via
  // ensureSession, or by opening an existing project chat). Null = project draft.
  const showThread = currentSessionId !== null;

  function newProjectChat() {
    // Back to a fresh project-bound draft → the project landing reappears.
    startProjectChat(projectId);
  }

  function confirmDelete() {
    menuRef.current?.close();
    confirmDeleteProject(projectId, () => {
      router.navigate("/(app)/(chat)" as never);
    });
  }

  return (
    <View className="flex-1 bg-background-neutral-00">
      {/* Header — sidebar toggle + project name + new-chat + actions menu */}
      <ScreenHeader>
        <Text
          font="main-ui-action"
          color="text-05"
          numberOfLines={1}
          style={{ flex: 1, marginLeft: 8 }}
        >
          {project?.name ?? "Project"}
        </Text>

        <Pressable
          onPress={newProjectChat}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="New chat in this project"
          className="rounded-[8px] p-1.5"
        >
          <SvgEditBig size={20} color={iconColor} />
        </Pressable>

        <Popover>
          <Popover.Trigger ref={menuRef} asChild>
            <Pressable
              hitSlop={10}
              accessibilityRole="button"
              accessibilityLabel="Project actions"
              className="rounded-[8px] p-1.5"
            >
              <SvgMoreHorizontal size={20} color={iconColor} />
            </Pressable>
          </Popover.Trigger>
          <Popover.Content side="bottom" align="end" sideOffset={6}>
            <Pressable
              onPress={confirmDelete}
              accessibilityRole="button"
              accessibilityLabel="Delete project"
              className="flex-row items-center gap-2 rounded-[8px] px-2 py-2 active:bg-background-tint-02"
            >
              <SvgTrash size={16} color={dangerColor} />
              <Text font="main-ui-body" color="action-text-danger-05">
                Delete Project
              </Text>
            </Pressable>
          </Popover.Content>
        </Popover>
      </ScreenHeader>

      {/* Body — project landing (draft) OR the live chat thread (active session).
          The composer inside ChatThreadBody stays mounted across the flip. */}
      <ChatThreadBody
        isError={isError}
        isLoading={hydrating}
        retry={retry}
        sessionId={currentSessionId}
        disabled={hydrating || isError}
        composerPaddingTop={4}
        body={
          showThread ? undefined : (
            <ScrollView
              style={{ flex: 1 }}
              contentContainerStyle={{ paddingBottom: 16 }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
            >
              <ProjectContextPanel
                projectId={projectId}
                project={project}
                files={files}
                isLoading={detailsLoading}
                onOpenInstructions={() => setInstructionsOpen(true)}
              />
              <View className="h-2" />
              <ProjectChatSessionList
                chats={chats}
                isLoading={detailsLoading && !details}
                onOpenChat={openExistingChat}
              />
            </ScrollView>
          )
        }
      />

      <AddInstructionModal
        visible={instructionsOpen}
        onClose={() => setInstructionsOpen(false)}
        projectId={projectId}
        initialInstructions={project?.instructions ?? null}
      />
    </View>
  );
}
