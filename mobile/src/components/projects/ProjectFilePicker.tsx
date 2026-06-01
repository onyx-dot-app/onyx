import { useRef, type ReactNode } from "react";
import { Dimensions, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgImage } from "@/components/icons/SvgImage";
import { SvgUploadSquare } from "@/components/icons/SvgUploadSquare";
import { ActionRow } from "@/components/chat/ActionRow";
import { RecentFileRow } from "@/components/chat/RecentFileRow";
import { useRecentFiles } from "@/query/files";
import { useFilePicker } from "@/chat/useFilePicker";
import {
  useLinkFileToProject,
  useUnlinkFileFromProject,
  useUploadProjectFiles,
} from "@/query/projects";
import { UserFileStatus, type ProjectFile } from "@/lib/types";

// Native mirror of web's FilePickerPopover inside ProjectContextPanel.

interface ProjectFilePickerProps {
  projectId: number;
  projectFileDbIds: Set<string>;
  trigger: ReactNode;
}

export function ProjectFilePicker({
  projectId,
  projectFileDbIds,
  trigger,
}: ProjectFilePickerProps) {
  const triggerRef = useRef<PopoverTriggerRef>(null);
  const insets = useSafeAreaInsets();

  const { data: recentFiles } = useRecentFiles();
  const recent = recentFiles ?? [];

  const upload = useUploadProjectFiles(projectId);
  const link = useLinkFileToProject(projectId);
  const unlink = useUnlinkFileFromProject(projectId);

  // No vision gate here — project uploads accept images.
  const { pickImages: runPickImages, pickDocuments: runPickDocuments } =
    useFilePicker();

  const screenWidth = Dimensions.get("window").width;
  const contentWidth = Math.min(320, screenWidth - 24);

  function close() {
    triggerRef.current?.close();
  }

  function pickImages() {
    close();
    void runPickImages((files) => upload.mutate(files));
  }

  function pickDocuments() {
    close();
    void runPickDocuments((files) => upload.mutate(files));
  }

  function toggleRecent(file: ProjectFile) {
    close();
    if (
      file.status === UserFileStatus.UPLOADING ||
      file.status === UserFileStatus.DELETING
    )
      return;
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
          icon={<SvgImage size={18} color="text-04" />}
          label="Photos"
          description="Add from your photo library"
          onPress={pickImages}
        />
        <ActionRow
          icon={<SvgUploadSquare size={18} color="text-04" />}
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
