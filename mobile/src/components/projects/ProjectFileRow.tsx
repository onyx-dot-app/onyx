import { Pressable, View } from "react-native";

import { Spinner, Text } from "@/components/opal";
import { SvgFileText } from "@/components/icons/SvgFileText";
import { SvgImage } from "@/components/icons/SvgImage";
import { SvgX } from "@/components/icons/SvgX";
import { fileExtensionLabel, isImageFile } from "@/lib/fileTypes";
import { UserFileStatus, type ProjectFile } from "@/lib/types";

// A single project file row (mobile analogue of web `FileCard`). Image/file glyph
// + name + a status sub-label, with a trailing remove (unlink) affordance. A busy
// file (uploading/processing) shows a spinner instead of the remove button.

function statusLabel(file: ProjectFile): string {
  switch (file.status) {
    case UserFileStatus.UPLOADING:
      return "Uploading…";
    case UserFileStatus.PROCESSING:
      return "Processing…";
    case UserFileStatus.FAILED:
      return "Failed";
    case UserFileStatus.DELETING:
      return "Removing…";
    default:
      return fileExtensionLabel(file.name) || "File";
  }
}

interface ProjectFileRowProps {
  file: ProjectFile;
  onRemove: (file: ProjectFile) => void;
}

export function ProjectFileRow({ file, onRemove }: ProjectFileRowProps) {
  const isBusy =
    file.status === UserFileStatus.PROCESSING ||
    file.status === UserFileStatus.UPLOADING ||
    file.status === UserFileStatus.DELETING;
  const isImg = isImageFile(file.name);
  const failed = file.status === UserFileStatus.FAILED;

  return (
    <View className="flex-row items-center gap-3 rounded-[12px] border border-border-01 px-3 py-2.5">
      <View className="h-5 w-5 items-center justify-center">
        {isBusy ? (
          <Spinner size={16} color="text-03" />
        ) : isImg ? (
          <SvgImage size={18} color="text-02" />
        ) : (
          <SvgFileText size={18} color="text-02" />
        )}
      </View>
      <View className="flex-1">
        <Text font="main-ui-body" color="text-04" numberOfLines={1}>
          {file.name}
        </Text>
        <Text
          font="secondary-body"
          color={failed ? "status-text-error-05" : "text-03"}
        >
          {statusLabel(file)}
        </Text>
      </View>
      <Pressable
        onPress={() => onRemove(file)}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={`Remove ${file.name}`}
        className="h-7 w-7 items-center justify-center rounded-[8px] active:bg-background-tint-02"
      >
        <SvgX size={16} color="text-02" />
      </Pressable>
    </View>
  );
}
