import { useMemo, useState } from "react";
import { ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router, useLocalSearchParams } from "expo-router";

import { useProjectDetails } from "@/api/chat/projects";
import { useProjectFiles } from "@/hooks/useProjectFiles";
import { useRecentFiles } from "@/hooks/useRecentFiles";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { ProjectFileList } from "@/components/chat/ProjectFileList";
import SvgChevronLeft from "@/icons/chevron-left";
import SvgPlus from "@/icons/plus";

// Lives off the /chat and /projects prefixes so deriveFocus returns null and the ChatSurface overlay hides.
export default function SourcesScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const parsed = Number(id);
  const projectId = id != null && Number.isFinite(parsed) ? parsed : null;

  const { data: details, isLoading } = useProjectDetails(projectId);
  const { files, addDocuments, addImages, linkRecent, removeFile } =
    useProjectFiles(projectId, details?.files);

  const [pickerOpen, setPickerOpen] = useState(false);
  const { data: recentFiles = [], isLoading: isLoadingRecent } =
    useRecentFiles(pickerOpen);
  const linkableRecent = useMemo(() => {
    const existing = new Set(files.map((file) => file.id));
    return recentFiles.filter((file) => !existing.has(file.id));
  }, [files, recentFiles]);

  return (
    <SafeAreaView edges={["top"]} className="flex-1 bg-background-neutral-00">
      <View className="flex-row items-center gap-8 px-12 py-8">
        <Button
          icon={SvgChevronLeft}
          prominence="tertiary"
          size="sm"
          accessibilityLabel="Back"
          onPress={() => router.back()}
        />
        <Text font="heading-h3" color="text-05" className="flex-1">
          Sources
        </Text>
        <Button
          icon={SvgPlus}
          prominence="primary"
          size="sm"
          accessibilityLabel="Add files"
          disabled={projectId == null}
          onPress={() => setPickerOpen(true)}
        />
      </View>

      <ScrollView
        className="flex-1"
        contentContainerClassName="gap-12 px-16 pb-24 pt-4"
        keyboardShouldPersistTaps="handled"
      >
        <Text font="secondary-body" color="text-02">
          Chats in this project can access these files.
        </Text>

        {isLoading && !details ? (
          <View className="items-center py-24">
            <Spinner size={20} />
          </View>
        ) : files.length === 0 ? (
          <View className="justify-center rounded-12 border border-dashed border-border-01 px-12 py-24">
            <Text font="secondary-body" color="text-02" className="text-center">
              No files in this project yet. Tap + to add.
            </Text>
          </View>
        ) : (
          <ProjectFileList
            files={files}
            onRemove={(fileId) => void removeFile(fileId)}
          />
        )}
      </ScrollView>

      <FilePickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onUploadDocuments={() => void addDocuments()}
        onUploadPhotos={() => void addImages()}
        recentFiles={linkableRecent}
        onPickRecent={(fileId) => void linkRecent(fileId)}
        isLoadingRecent={isLoadingRecent}
      />
    </SafeAreaView>
  );
}
