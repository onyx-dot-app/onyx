import { useRef, type ReactNode } from "react";
import { Alert, Dimensions, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { ImageIcon, UploadSquareIcon } from "@/components/ui/icons";
import { RecentFileRow } from "@/components/chat/RecentFileRow";
import { useToken } from "@/theme/ThemeProvider";
import { useRecentFiles } from "@/query/files";
import {
  useLinkFileToProject,
  useUnlinkFileFromProject,
  useUploadProjectFiles,
} from "@/query/projects";
import type { UploadableFile } from "@/lib/api";
import { UserFileStatus, type ProjectFile } from "@/lib/types";

// Native mirror of web's `FilePickerPopover` as used inside ProjectContextPanel:
// an anchored opal Popover with Photos / Upload File and the recent-files list,
// where tapping a recent file LINKS it to (or UNLINKS it from) this project, and
// fresh picks upload with the project_id attached.

// Best-effort filename from a local URI when the picker reports none.
function nameFromUri(uri: string, fallback: string): string {
  const seg = (uri.split("/").pop() ?? "").split("?")[0] ?? "";
  return seg.includes(".") ? decodeURIComponent(seg) : fallback;
}

interface ActionRowProps {
  icon: ReactNode;
  label: string;
  description: string;
  onPress: () => void;
}

function ActionRow({ icon, label, description, onPress }: ActionRowProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      className="flex-row items-center gap-3 rounded-[8px] px-2 py-2 active:bg-background-tint-02"
    >
      <View className="h-5 w-5 items-center justify-center">{icon}</View>
      <View className="flex-1">
        <Text font="main-ui-body" color="text-05" numberOfLines={1}>
          {label}
        </Text>
        <Text font="secondary-body" color="text-03" numberOfLines={1}>
          {description}
        </Text>
      </View>
    </Pressable>
  );
}

interface ProjectFilePickerProps {
  projectId: number;
  /** DB ids (`ProjectFile.id`) of files already linked to this project. */
  projectFileDbIds: Set<string>;
  /** The "Add Files" element used as the popover trigger (`asChild`). */
  trigger: ReactNode;
}

export function ProjectFilePicker({
  projectId,
  projectFileDbIds,
  trigger,
}: ProjectFilePickerProps) {
  const triggerRef = useRef<PopoverTriggerRef>(null);
  const insets = useSafeAreaInsets();
  const iconColor = useToken("text-04");

  const { data: recentFiles } = useRecentFiles();
  const recent = recentFiles ?? [];

  const upload = useUploadProjectFiles(projectId);
  const link = useLinkFileToProject(projectId);
  const unlink = useUnlinkFileFromProject(projectId);

  const screenWidth = Dimensions.get("window").width;
  const contentWidth = Math.min(320, screenWidth - 24);

  function close() {
    triggerRef.current?.close();
  }

  async function pickImages() {
    close();
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsMultipleSelection: true,
        quality: 1,
      });
      if (result.canceled) return;
      const files: UploadableFile[] = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.fileName ?? nameFromUri(asset.uri, "image.jpg"),
        mimeType: asset.mimeType,
      }));
      if (files.length > 0) upload.mutate(files);
    } catch {
      Alert.alert("Couldn't open photos", "Please try again.");
    }
  }

  async function pickDocuments() {
    close();
    try {
      const result = await DocumentPicker.getDocumentAsync({
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      const files: UploadableFile[] = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType,
      }));
      if (files.length > 0) upload.mutate(files);
    } catch {
      Alert.alert("Couldn't open files", "Please try again.");
    }
  }

  function toggleRecent(file: ProjectFile) {
    close();
    if (file.status === UserFileStatus.UPLOADING) return;
    if (file.status === UserFileStatus.DELETING) return;
    if (projectFileDbIds.has(file.id)) unlink.mutate(file.id);
    else link.mutate(file);
  }

  return (
    <Popover>
      <Popover.Trigger ref={triggerRef} asChild>
        {trigger}
      </Popover.Trigger>
      <Popover.Content
        side="bottom"
        align="end"
        sideOffset={8}
        insets={{
          top: insets.top + 8,
          bottom: insets.bottom + 8,
          left: 12,
          right: 12,
        }}
        style={{ width: contentWidth }}
      >
        <ActionRow
          icon={<ImageIcon size={18} color={iconColor} />}
          label="Photos"
          description="Add from your photo library"
          onPress={pickImages}
        />
        <ActionRow
          icon={<UploadSquareIcon size={18} color={iconColor} />}
          label="Upload File"
          description="Choose a document from your device"
          onPress={pickDocuments}
        />

        {recent.length > 0 ? (
          <>
            <View className="my-1 h-[1px] bg-border-02" />
            <Text
              font="secondary-body"
              color="text-02"
              style={{ paddingHorizontal: 8, paddingTop: 4, paddingBottom: 2 }}
            >
              Recent Files
            </Text>
            <ScrollView
              style={{ maxHeight: 240 }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
            >
              {recent.map((file) => (
                <RecentFileRow
                  key={file.id}
                  file={file}
                  attached={projectFileDbIds.has(file.id)}
                  onToggle={toggleRecent}
                />
              ))}
            </ScrollView>
          </>
        ) : null}
      </Popover.Content>
    </Popover>
  );
}
