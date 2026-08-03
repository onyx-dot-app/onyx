import { useRef } from "react";
import { Modal, Platform, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/components/ui/button";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import {
  UserFileStatus,
  isProcessingStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { extensionOf, isImageName } from "@/lib/files";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgUploadSquare from "@/icons/upload-square";
import SvgX from "@/icons/x";

interface FilePickerSheetProps {
  visible: boolean;
  onClose: () => void;
  onUploadDocuments: () => void;
  onUploadPhotos: () => void;
  // Recent library files not already linked to this project.
  recentFiles: ProjectFile[];
  onPickRecent: (fileId: string) => void;
  isLoadingRecent: boolean;
}

// Mirrors web's FilePickerPopover, as a bottom sheet instead of a hover popover.
export function FilePickerSheet({
  visible,
  onClose,
  onUploadDocuments,
  onUploadPhotos,
  recentFiles,
  onPickRecent,
  isLoadingRecent,
}: FilePickerSheetProps) {
  const insets = useSafeAreaInsets();

  // iOS drops a picker presented while this Modal is still dismissing, so defer the action to
  // onDismiss (after the sheet is gone); Android has no such conflict and runs immediately.
  const pendingRef = useRef<(() => void) | null>(null);
  const choose = (action: () => void) => {
    onClose();
    if (Platform.OS === "ios") pendingRef.current = action;
    else action();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      onDismiss={() => {
        const action = pendingRef.current;
        pendingRef.current = null;
        action?.();
      }}
      statusBarTranslucent
    >
      {/* Semantic color tokens can't express translucency (bare CSS vars, no alpha channel), so the
          dimming scrim uses a raw rgba — the one place a non-token color is warranted. */}
      <Pressable
        className="flex-1 justify-end"
        style={{ backgroundColor: "rgba(0, 0, 0, 0.4)" }}
        onPress={onClose}
      >
        {/* Stop taps inside the sheet from dismissing it. */}
        <Pressable
          onPress={() => {}}
          className="rounded-t-20 border-t border-border-01 bg-background-tint-00 px-16 pt-16"
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View className="mb-8 flex-row items-center justify-between">
            <Text font="main-content-emphasis" color="text-04">
              Add files
            </Text>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              accessibilityLabel="Close"
              onPress={onClose}
            />
          </View>

          <LineItemButton
            icon={SvgUploadSquare}
            title="Upload from device"
            description="Documents, text, PDFs"
            sizePreset="main-ui"
            variant="section"
            onPress={() => choose(onUploadDocuments)}
          />
          <LineItemButton
            icon={SvgImage}
            title="Choose photos"
            description="From your photo library"
            sizePreset="main-ui"
            variant="section"
            onPress={() => choose(onUploadPhotos)}
          />

          <View className="py-8">
            <Separator />
          </View>

          <Text font="secondary-body" color="text-02" className="px-8 pb-4">
            Recent files
          </Text>

          {isLoadingRecent && recentFiles.length === 0 ? (
            <View className="items-center py-16">
              <Spinner size={20} />
            </View>
          ) : recentFiles.length === 0 ? (
            <View className="px-8 py-12">
              <Text font="secondary-body" color="text-02">
                No recent files to add.
              </Text>
            </View>
          ) : (
            <ScrollView
              className="max-h-[280px]"
              keyboardShouldPersistTaps="handled"
            >
              {recentFiles.map((file) => {
                const processing = isProcessingStatus(file.status);
                const uploading =
                  String(file.status).toUpperCase() ===
                  UserFileStatus.UPLOADING;
                return (
                  <LineItemButton
                    key={file.id}
                    leading={processing ? <Spinner size={16} /> : undefined}
                    icon={isImageName(file.name) ? SvgImage : SvgFileText}
                    title={file.name}
                    description={
                      uploading
                        ? "Uploading…"
                        : processing
                          ? "Indexing…"
                          : extensionOf(file.name) || "File"
                    }
                    titleMaxLines={1}
                    sizePreset="main-ui"
                    variant="section"
                    disabled={uploading}
                    onPress={() => choose(() => onPickRecent(file.id))}
                  />
                );
              })}
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}
