import { useMemo, useState } from "react";
import { Pressable, TextInput, View } from "react-native";

import { Button, Text } from "@/components/opal";
import {
  SvgAddLines,
  SvgEdit,
  SvgFolderOpen,
  SvgPlusCircle,
} from "@/components/icons";
import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";
import { useRenameProject, useUnlinkFileFromProject } from "@/query/projects";
import type { Project, ProjectFile } from "@/lib/types";
import { ProjectFileRow } from "./ProjectFileRow";
import { ProjectFilePicker } from "./ProjectFilePicker";

// Native mirror of web `ProjectContextPanel`. Folder glyph + editable name, a
// divider, an Instructions section (current text + "Set Instructions"), and a
// Files section ("Add Files" + the linked-file list, or an empty dashed prompt).
// Colors/typography use the same Opal tokens as web (text-04 headers, text-02
// body, border-01 dashes).

interface ProjectContextPanelProps {
  projectId: number;
  project: Project | undefined;
  files: ProjectFile[];
  isLoading: boolean;
  /** Opens the Set-Instructions sheet (owned by the screen). */
  onOpenInstructions: () => void;
}

export function ProjectContextPanel({
  projectId,
  project,
  files,
  isLoading,
  onOpenInstructions,
}: ProjectContextPanelProps) {
  const folderColor = useToken("text-04");
  const editColor = useToken("text-03");
  const typedColor = useToken("text-04");

  const rename = useRenameProject();
  const unlink = useUnlinkFileFromProject(projectId);

  const [isEditingName, setIsEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");

  // Seed the draft from the current name the moment editing begins (no effect —
  // avoids the set-state-in-effect cascade lint and is simpler).
  function startEditing() {
    setDraftName(project?.name ?? "");
    setIsEditingName(true);
  }

  const projectName = project?.name ?? "Loading project...";
  const instructions = project?.instructions;
  const projectFileDbIds = useMemo(
    () => new Set(files.map((f) => f.id)),
    [files],
  );

  async function commitRename() {
    const next = draftName.trim();
    setIsEditingName(false);
    if (next && next !== project?.name) {
      try {
        await rename.mutateAsync({ projectId, name: next });
      } catch {
        // Rollback is handled by the mutation; nothing to do here.
      }
    }
  }

  return (
    <View className="gap-6 px-4 pb-2 pt-4">
      {/* Folder glyph + editable project name (web: SvgFolderOpen + heading-h2) */}
      <View className="gap-1">
        <SvgFolderOpen size={32} color={folderColor} />
        {isEditingName ? (
          <TextInput
            value={draftName}
            onChangeText={setDraftName}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={commitRename}
            onBlur={commitRename}
            style={[typography["heading-h2"], { color: typedColor, padding: 0 }]}
          />
        ) : (
          <View className="flex-row items-center gap-2">
            <Text font="heading-h2" color="text-04" numberOfLines={1}>
              {projectName}
            </Text>
            <Pressable
              onPress={startEditing}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="Edit project name"
              className="h-7 w-7 items-center justify-center rounded-[8px] active:bg-background-tint-02"
            >
              <SvgEdit size={16} color={editColor} />
            </Pressable>
          </View>
        )}
      </View>

      <View className="h-[1px] bg-border-01" />

      {/* Instructions */}
      <View className="flex-row items-start justify-between gap-2">
        <View className="min-w-0 flex-1 gap-0.5">
          <Text font="heading-h3" color="text-04">
            Instructions
          </Text>
          {isLoading && !project ? (
            <View className="h-4 w-3/4 rounded-[4px] bg-background-tint-02" />
          ) : (
            <Text font="secondary-body" color="text-02" numberOfLines={2}>
              {instructions
                ? instructions
                : "Add instructions to tailor the response in this project."}
            </Text>
          )}
        </View>
        <Button
          variant="default"
          prominence="tertiary"
          size="sm"
          leftIcon={<SvgAddLines size={16} color={folderColor} />}
          onPress={onOpenInstructions}
        >
          Set Instructions
        </Button>
      </View>

      {/* Files */}
      <View className="gap-2">
        <View className="flex-row items-start justify-between gap-2">
          <View className="min-w-0 flex-1 gap-0.5">
            <Text font="heading-h3" color="text-04">
              Files
            </Text>
            <Text font="secondary-body" color="text-02">
              Chats in this project can access these files.
            </Text>
          </View>
          <ProjectFilePicker
            projectId={projectId}
            projectFileDbIds={projectFileDbIds}
            trigger={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Add files"
                className="h-8 flex-row items-center gap-1 rounded-[8px] px-3 active:bg-background-tint-02"
              >
                <SvgPlusCircle size={16} color={folderColor} />
                <Text font="secondary-action" color="text-04">
                  Add Files
                </Text>
              </Pressable>
            }
          />
        </View>

        {isLoading && !project ? (
          <View className="h-[60px] rounded-[12px] bg-background-tint-02" />
        ) : files.length > 0 ? (
          <View className="gap-2">
            {files.map((file) => (
              <ProjectFileRow
                key={file.id}
                file={file}
                onRemove={(f) => unlink.mutate(f.id)}
              />
            ))}
          </View>
        ) : (
          <View className="rounded-[12px] border border-dashed border-border-01 px-3 py-4">
            <Text font="secondary-body" color="text-02">
              Add documents, texts, or images to use in the project.
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}
