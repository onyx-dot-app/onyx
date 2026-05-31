import { useRef, useState, type ReactNode } from "react";
import { Alert, Dimensions, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import {
  ImageIcon,
  MoreHorizontalIcon,
  UploadSquareIcon,
} from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { useRecentFiles } from "@/query/files";
import { isImageFile } from "@/lib/fileTypes";
import type { UploadableFile } from "@/lib/api";
import type { ProjectFile } from "@/lib/types";
import { RecentFileRow } from "./RecentFileRow";
import { RecentFilesModal } from "./RecentFilesModal";

// AttachMenu — native mirror of web `FilePickerPopover`. An opal Popover anchored
// to the composer's paperclip with: Photos, Upload File, a divider, the Recent
// Files quick-list (≤3, re-attach without re-upload), and an "All Recent Files"
// overflow that opens the full modal. No camera (per product). Opens upward from
// the bottom-left of the composer.

// Web `MAX_FILES_TO_SHOW` — recent files shown inline before the overflow row.
const MAX_FILES_TO_SHOW = 3;

const VISION_MSG =
  "The current model does not support image input. Pick a model with Vision support to attach images.";

interface AttachMenuProps {
  /** The paperclip element used as the popover trigger (`asChild`). */
  trigger: ReactNode;
  /** Whether the active model accepts images (vision gate). */
  imagesAllowed: boolean;
  /** `file_id`s already attached — drives the check mark + pick/unpick toggle. */
  attachedFileIds: string[];
  onPickImages: (files: UploadableFile[]) => void;
  onPickDocuments: (files: UploadableFile[]) => void;
  onPickRecent: (file: ProjectFile) => void;
  onUnpickRecent: (file: ProjectFile) => void;
}

// Best-effort filename from a local URI when the picker gives none.
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

export function AttachMenu({
  trigger,
  imagesAllowed,
  attachedFileIds,
  onPickImages,
  onPickDocuments,
  onPickRecent,
  onUnpickRecent,
}: AttachMenuProps) {
  const triggerRef = useRef<PopoverTriggerRef>(null);
  const insets = useSafeAreaInsets();
  const iconColor = useToken("text-04");
  const [modalVisible, setModalVisible] = useState(false);

  const { data: recentFiles } = useRecentFiles();
  const recent = recentFiles ?? [];
  const attachedSet = new Set(attachedFileIds);

  const screenWidth = Dimensions.get("window").width;
  const contentWidth = Math.min(300, screenWidth - 24);

  function close() {
    triggerRef.current?.close();
  }

  async function pickImages() {
    close();
    if (!imagesAllowed) {
      Alert.alert("Images not supported", VISION_MSG);
      return;
    }
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
      if (files.length > 0) onPickImages(files);
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
      let files: UploadableFile[] = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType,
      }));
      // The document picker can return images too — enforce the same vision gate
      // here so it can't bypass the Photos guard (web gates at the upload layer).
      if (!imagesAllowed) {
        const hadImages = files.some((file) => isImageFile(file.name));
        files = files.filter((file) => !isImageFile(file.name));
        if (hadImages) Alert.alert("Images not supported", VISION_MSG);
      }
      if (files.length > 0) onPickDocuments(files);
    } catch {
      Alert.alert("Couldn't open files", "Please try again.");
    }
  }

  function toggleRecent(file: ProjectFile) {
    close();
    if (attachedSet.has(file.file_id)) onUnpickRecent(file);
    else onPickRecent(file);
  }

  const quickFiles = recent.slice(0, MAX_FILES_TO_SHOW);
  const hasOverflow = recent.length > MAX_FILES_TO_SHOW;

  return (
    <>
      <RecentFilesModal
        visible={modalVisible}
        onClose={() => setModalVisible(false)}
        files={recent}
        attachedFileIds={attachedFileIds}
        onToggle={(file) => {
          if (attachedSet.has(file.file_id)) onUnpickRecent(file);
          else onPickRecent(file);
        }}
      />

      <Popover>
        <Popover.Trigger ref={triggerRef} asChild>
          {trigger}
        </Popover.Trigger>
        <Popover.Content
          side="top"
          align="start"
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

          {quickFiles.length > 0 ? (
            <>
              <View className="my-1 h-[1px] bg-border-02" />
              <Text
                font="secondary-body"
                color="text-02"
                style={{ paddingHorizontal: 8, paddingTop: 4, paddingBottom: 2 }}
              >
                Recent Files
              </Text>
              {quickFiles.map((file) => (
                <RecentFileRow
                  key={file.id}
                  file={file}
                  attached={attachedSet.has(file.file_id)}
                  onToggle={toggleRecent}
                />
              ))}
              {hasOverflow ? (
                <ActionRow
                  icon={<MoreHorizontalIcon size={18} color={iconColor} />}
                  label="All Recent Files"
                  description="Browse everything you've uploaded"
                  onPress={() => {
                    close();
                    setModalVisible(true);
                  }}
                />
              ) : null}
            </>
          ) : null}
        </Popover.Content>
      </Popover>
    </>
  );
}
