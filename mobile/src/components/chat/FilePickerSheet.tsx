import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/components/ui/button";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Separator } from "@/components/ui/separator";
import { Text } from "@/components/ui/text";
import type { ProjectFile } from "@/chat/contracts/projects";
import { extensionOf, isImageName } from "@/lib/files";
import SvgFileSmall from "@/icons/file-small";
import SvgFileText from "@/icons/file-text";
import SvgImageSmall from "@/icons/image-small";
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

// Add-files chooser (mirrors web's FilePickerPopover). Web uses a hover popover;
// mobile uses a bottom sheet.
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

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable
        className="bg-background-inverted-05/40 flex-1 justify-end"
        onPress={onClose}
      >
        {/* Stop taps inside the sheet from dismissing it. */}
        <Pressable
          onPress={() => {}}
          className="rounded-t-24 border-t border-border-01 bg-background-tint-00 px-16 pt-16"
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
            icon={SvgFileSmall}
            title="Upload from device"
            description="Documents, text, PDFs"
            sizePreset="main-ui"
            variant="section"
            onPress={onUploadDocuments}
          />
          <LineItemButton
            icon={SvgImageSmall}
            title="Choose photos"
            description="From your photo library"
            sizePreset="main-ui"
            variant="section"
            onPress={onUploadPhotos}
          />

          <View className="py-8">
            <Separator />
          </View>

          <Text font="secondary-body" color="text-02" className="px-8 pb-4">
            Recent files
          </Text>

          {isLoadingRecent ? (
            <View className="py-16">
              <ActivityIndicator size="small" />
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
              {recentFiles.map((file) => (
                <LineItemButton
                  key={file.id}
                  icon={isImageName(file.name) ? SvgImageSmall : SvgFileText}
                  title={file.name}
                  description={extensionOf(file.name) || "File"}
                  titleMaxLines={1}
                  sizePreset="main-ui"
                  variant="section"
                  onPress={() => onPickRecent(file.id)}
                />
              ))}
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}
