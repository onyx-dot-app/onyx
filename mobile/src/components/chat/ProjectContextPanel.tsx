import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";

import { useRecentFiles } from "@/api/files/files";
import { Button } from "@/components/ui/button";
import { Content, ContentAction } from "@/components/ui/content";
import { Text } from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { FileCard } from "@/components/chat/FileCard";
import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { useProjectFiles } from "@/hooks/useProjectFiles";
import SvgFolder from "@/icons/folder";
import SvgPlus from "@/icons/plus";
import type { ProjectDetails } from "@/chat/contracts/projects";

interface ProjectContextPanelProps {
  projectId: number | null;
  details?: ProjectDetails;
  isLoading: boolean;
}

// Project detail + file management (mirrors web's ProjectContextPanel).
export function ProjectContextPanel({
  projectId,
  details,
  isLoading,
}: ProjectContextPanelProps) {
  const project = details?.project;
  const instructions = project?.instructions?.trim();
  const loadingDetails = isLoading && !details;

  const [pickerOpen, setPickerOpen] = useState(false);
  const {
    files,
    progressById,
    errors,
    isBusy,
    addDocuments,
    addImages,
    linkRecent,
    removeFile,
    dismissErrors,
  } = useProjectFiles(projectId, details?.files);

  // Recent library files, fetched only while the picker is open.
  const { data: recentFiles = [], isLoading: isLoadingRecent } =
    useRecentFiles(pickerOpen);
  const linkableRecent = useMemo(() => {
    const existingIds = new Set(files.map((file) => file.id));
    return recentFiles.filter((file) => !existingIds.has(file.id));
  }, [files, recentFiles]);

  return (
    <View className="gap-24">
      <Content icon={SvgFolder} title={project?.name ?? "Loading project…"} />

      <Separator />

      <Content
        sizePreset="main-ui"
        variant="section"
        title="Instructions"
        description={instructions || "No instructions for this project."}
        descriptionMaxLines={4}
      />

      <View className="gap-8">
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          title="Files"
          description="Chats in this project can access these files."
          rightChildren={
            <Button
              icon={SvgPlus}
              prominence="secondary"
              size="sm"
              accessibilityLabel="Add files"
              disabled={projectId == null || loadingDetails || isBusy}
              onPress={() => setPickerOpen(true)}
            />
          }
        />

        {errors.length > 0 ? (
          <Pressable
            onPress={dismissErrors}
            className="gap-4 rounded-12 border border-border-01 px-12 py-8"
          >
            {errors.map((message, index) => (
              <Text
                key={`${index}:${message}`}
                font="secondary-body"
                color="status-error-05"
              >
                {message}
              </Text>
            ))}
            <Text font="secondary-body" color="text-03">
              Tap to dismiss
            </Text>
          </Pressable>
        ) : null}

        {loadingDetails ? (
          <ActivityIndicator size="small" />
        ) : files.length === 0 ? (
          <View className="justify-center rounded-12 border border-dashed border-border-01 px-12 py-12">
            <Text font="secondary-body" color="text-02">
              No files in this project yet.
            </Text>
          </View>
        ) : (
          <View className="gap-8">
            {files.map((file) => (
              <FileCard
                key={file.id}
                file={file}
                progress={progressById.get(file.id)}
                onRemove={() => {
                  void removeFile(file.id);
                }}
              />
            ))}
          </View>
        )}
      </View>

      <FilePickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onUploadDocuments={() => {
          setPickerOpen(false);
          void addDocuments();
        }}
        onUploadPhotos={() => {
          setPickerOpen(false);
          void addImages();
        }}
        recentFiles={linkableRecent}
        onPickRecent={(fileId) => {
          setPickerOpen(false);
          void linkRecent(fileId);
        }}
        isLoadingRecent={isLoadingRecent}
      />
    </View>
  );
}
