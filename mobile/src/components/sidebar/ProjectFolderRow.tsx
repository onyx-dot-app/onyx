import { useRef, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { router } from "expo-router";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgEdit, SvgFolder, SvgFolderOpen, SvgTrash } from "@/components/icons";
import { SvgMoreHorizontal } from "@/components/icons/SvgMoreHorizontal";
import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";
import { useDrawer } from "@/components/drawer/DrawerProvider";
import { useStartProjectChat } from "@/chat/useStartProjectChat";
import { useOpenExistingChat } from "@/chat/useOpenExistingChat";
import { useConfirmDeleteProject } from "@/chat/confirmDeleteProject";
import { useRenameProject } from "@/query/projects";
import { chatDisplayName } from "@/lib/chatLabels";
import type { Project } from "@/lib/types";
import { SidebarRow } from "./SidebarRow";

// Native mirror of web ProjectFolderButton.

interface ProjectFolderRowProps {
  project: Project;
}

export function ProjectFolderRow({ project }: ProjectFolderRowProps) {
  const { close } = useDrawer();
  const startProjectChat = useStartProjectChat();
  const openExistingChat = useOpenExistingChat();
  const confirmDeleteProject = useConfirmDeleteProject();
  const rename = useRenameProject();

  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(project.name);
  const menuRef = useRef<PopoverTriggerRef>(null);

  const iconColor = useToken("text-03");
  const dangerColor = useToken("action-text-danger-05");

  function openProject() {
    // Fresh project-bound draft → no thread.
    startProjectChat(project.id);
    close();
    router.navigate(`/(app)/projects/${project.id}` as never);
  }

  function openChat(chatSessionId: string) {
    openExistingChat(chatSessionId);
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
    confirmDeleteProject(project.id);
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
            <SvgFolderOpen size={18} color={iconColor} />
          ) : (
            <SvgFolder size={18} color={iconColor} />
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
              { color: iconColor, flex: 1, padding: 0 },
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
              <SvgMoreHorizontal size={18} color={iconColor} />
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
              <SvgEdit size={16} color={iconColor} />
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

      {expanded
        ? project.chat_sessions.map((chat) => (
            <View key={chat.id} style={{ paddingLeft: 16 }}>
              <SidebarRow
                label={chatDisplayName(chat.name)}
                onPress={() => openChat(chat.id)}
              />
            </View>
          ))
        : null}
    </View>
  );
}
