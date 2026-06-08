import { useRef, useState, type ReactNode } from "react";
import { View } from "react-native";

import { Popover, Text, type PopoverTriggerRef } from "@/components/opal";
import { SvgImage } from "@/components/icons/SvgImage";
import { SvgMoreHorizontal } from "@/components/icons/SvgMoreHorizontal";
import { SvgUploadSquare } from "@/components/icons/SvgUploadSquare";
import { useRecentFiles } from "@/query/files";
import { useFilePicker } from "@/chat/useFilePicker";
import type { UploadableFile } from "@/lib/api";
import type { ProjectFile } from "@/lib/types";
import { ActionRow } from "./ActionRow";
import { usePopoverPlacement } from "./usePopoverPlacement";
import { RecentFileRow } from "./RecentFileRow";
import { RecentFilesModal } from "./RecentFilesModal";

// Native mirror of web FilePickerPopover. No camera (per product).

// Web MAX_FILES_TO_SHOW — recent files shown inline before the overflow row.
const MAX_FILES_TO_SHOW = 3;

interface AttachMenuProps {
  trigger: ReactNode;
  // Whether the active model accepts images (vision gate).
  imagesAllowed: boolean;
  // file_ids already attached — drives the check mark + pick/unpick toggle.
  attachedFileIds: string[];
  onPickImages: (files: UploadableFile[]) => void;
  onPickDocuments: (files: UploadableFile[]) => void;
  onPickRecent: (file: ProjectFile) => void;
  onUnpickRecent: (file: ProjectFile) => void;
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
  const [modalVisible, setModalVisible] = useState(false);

  const { data: recentFiles } = useRecentFiles();
  const recent = recentFiles ?? [];
  const attachedSet = new Set(attachedFileIds);

  // Vision gate lives in the shared picker (blocks image picks for non-vision models).
  const { pickImages: runPickImages, pickDocuments: runPickDocuments } =
    useFilePicker({ imagesAllowed });

  const { insets, contentWidth } = usePopoverPlacement({
    maxWidth: 300,
    widthMargin: 24,
  });

  function close() {
    triggerRef.current?.close();
  }

  function pickImages() {
    close();
    void runPickImages(onPickImages);
  }

  function pickDocuments() {
    close();
    void runPickDocuments(onPickDocuments);
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
        onToggle={toggleRecent}
      />

      <Popover>
        <Popover.Trigger ref={triggerRef} asChild>
          {trigger}
        </Popover.Trigger>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={8}
          insets={insets}
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
                  icon={<SvgMoreHorizontal size={18} color="text-04" />}
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
