import { useRef, useState } from "react";
import { Alert, Pressable, TextInput, View } from "react-native";
import { router } from "expo-router";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgEdit, SvgFolder, SvgFolderOpen, SvgTrash } from "@/components/icons";
import { MoreHorizontalIcon } from "@/components/ui/icons";
import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";
import { useDrawer } from "@/components/drawer/DrawerProvider";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useProjectChatTarget } from "@/state/projectChatTarget";
import { useStartProjectChat } from "@/chat/useStartProjectChat";
import { useRenameProject, useDeleteProject } from "@/query/projects";
import type { Project } from "@/lib/types";
import { SidebarRow } from "./SidebarRow";

// Sidebar project row — mobile mirror of web `ProjectFolderButton`. The folder
// glyph toggles an inline list of the project's chats; the name navigates to the
// project screen; the ⋯ menu offers Rename (inline) / Delete (confirm).

const UNNAMED_CHAT = "New Chat";

interface ProjectFolderRowProps {
  project: Project;
}

export function ProjectFolderRow({ project }: ProjectFolderRowProps) {
  const { close } = useDrawer();
  const setCurrentSession = useChatSessionStore((s) => s.setCurrentSession);
  const startProjectChat = useStartProjectChat();
  const rename = useRenameProject();
  const deleteProject = useDeleteProject();

  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(project.name);
  const menuRef = useRef<PopoverTriggerRef>(null);

  const folderColor = useToken("text-03");
  const nameColor = useToken("text-03");
  const menuColor = useToken("text-03");
  const dangerColor = useToken("action-text-danger-05");

  function openProject() {
    // Enter the project at its landing (fresh project-bound draft → no thread).
    startProjectChat(project.id);
    close();
    router.navigate(`/(app)/projects/${project.id}` as never);
  }

  function openChat(chatSessionId: string) {
    useProjectChatTarget.getState().clear();
    setCurrentSession(chatSessionId);
    close();
    router.navigate("/(app)/(chat)" as never);
  }

  async function commitRename() {
    const next = draftName.trim();
    setIsEditing(false);
    if (next && next !== project.name) {
      try {
        await rename.mutateAsync({ projectId: project.id, name: next });
      } catch {
        setDraftName(project.name);
      }
    } else {
      setDraftName(project.name);
    }
  }

  function confirmDelete() {
    menuRef.current?.close();
    Alert.alert(
      "Delete Project",
      "Are you sure you want to delete this project? This action cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            // If a pending project-chat launcher targeted this project, drop it
            // so the next draft can't be sent with a deleted project_id.
            if (useProjectChatTarget.getState().projectId === project.id) {
              useProjectChatTarget.getState().clear();
            }
            deleteProject.mutate(project.id);
          },
        },
      ],
    );
  }

  return (
    <View>
      <View className="mx-2 h-10 flex-row items-center rounded-[8px] px-2 active:bg-background-tint-03">
        <Pressable
          onPress={() => setExpanded((v) => !v)}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel={expanded ? "Collapse project" : "Expand project"}
          className="mr-2 h-7 w-7 items-center justify-center"
        >
          {expanded ? (
            <SvgFolderOpen size={18} color={folderColor} />
          ) : (
            <SvgFolder size={18} color={folderColor} />
          )}
        </Pressable>

        {isEditing ? (
          <TextInput
            value={draftName}
            onChangeText={setDraftName}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={commitRename}
            onBlur={commitRename}
            style={[
              typography["main-ui-body"],
              { color: nameColor, flex: 1, padding: 0 },
            ]}
          />
        ) : (
          <Pressable onPress={openProject} className="flex-1" accessibilityRole="button">
            <Text font="main-ui-body" color="text-03" numberOfLines={1}>
              {project.name}
            </Text>
          </Pressable>
        )}

        <Popover>
          <Popover.Trigger ref={menuRef} asChild>
            <Pressable
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="Project actions"
              className="h-7 w-7 items-center justify-center rounded-[8px]"
            >
              <MoreHorizontalIcon size={18} color={menuColor} />
            </Pressable>
          </Popover.Trigger>
          <Popover.Content side="bottom" align="end" sideOffset={6}>
            <Pressable
              onPress={() => {
                menuRef.current?.close();
                setIsEditing(true);
              }}
              accessibilityRole="button"
              accessibilityLabel="Rename project"
              className="flex-row items-center gap-2 rounded-[8px] px-2 py-2 active:bg-background-tint-02"
            >
              <SvgEdit size={16} color={menuColor} />
              <Text font="main-ui-body" color="text-04">
                Rename Project
              </Text>
            </Pressable>
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
      </View>

      {/* Inline chat sessions (web: expanded ProjectFolderButton lists ChatButtons) */}
      {expanded
        ? project.chat_sessions.map((chat) => (
            <View key={chat.id} style={{ paddingLeft: 16 }}>
              <SidebarRow
                label={(chat.name ?? "").trim() || UNNAMED_CHAT}
                onPress={() => openChat(chat.id)}
              />
            </View>
          ))
        : null}
    </View>
  );
}
