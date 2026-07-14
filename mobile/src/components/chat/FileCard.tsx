import { memo } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";

import { AttachmentImage } from "@/components/chat/AttachmentImage";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import {
  isProcessingStatus,
  UserFileStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import { attachmentStatusLabel, isFailedFile, isImageName } from "@/lib/files";
import { cn } from "@/lib/utils";
import { useUploadProgress } from "@/state/userFileStore";
import SvgAlertCircle from "@/icons/alert-circle";
import SvgFileText from "@/icons/file-text";
import SvgX from "@/icons/x";

const IMAGE_SIZE = 64;

interface FileCardProps {
  file: ProjectFile;
  // Omit for a read-only card (a sent message's files).
  onRemove?: (id: string) => void;
}

function isImage(file: ProjectFile): boolean {
  return file.chat_file_type === ChatFileType.IMAGE || isImageName(file.name);
}

// The single file-display card (mirrors web's FileCard), used by the composer strip, a
// sent message's attachments, and the project panel. Images render as a square thumbnail;
// everything else — and any failed upload — as a bordered pill. Removable once the upload
// lands (matches web); a file stuck INDEXING/FAILED stays removable so the user can unblock
// send.
// Memoized so it skips the composer strip's per-keystroke re-renders. Progress is read from the
// store by this card's own atomic selector, so a tick re-renders only this card.
export const FileCard = memo(function FileCard({
  file,
  onRemove,
}: FileCardProps) {
  const progress = useUploadProgress(file.id);
  const uploading =
    String(file.status).toUpperCase() === UserFileStatus.UPLOADING;
  const canRemove = onRemove != null && !uploading;

  if (isImage(file) && !isFailedFile(file)) {
    return (
      <View className="relative" testID="file-image-card">
        <View
          className="items-center justify-center overflow-hidden rounded-08 border border-border-01"
          style={{ width: IMAGE_SIZE, height: IMAGE_SIZE }}
        >
          {uploading ? (
            <ActivityIndicator size="small" />
          ) : (
            <AttachmentImage fileId={file.file_id} size={IMAGE_SIZE} />
          )}
        </View>
        {canRemove ? (
          <Pressable
            onPress={() => onRemove(file.id)}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${file.name}`}
            style={{ top: -6, right: -6 }}
            className="bg-background-inverted-05 absolute h-20 w-20 items-center justify-center rounded-full border border-border-01"
          >
            <Icon as={SvgX} size={12} className="text-text-inverted-05" />
          </Pressable>
        ) : null}
      </View>
    );
  }

  const processing = isProcessingStatus(file.status);
  const failed = isFailedFile(file);
  return (
    <View
      testID="file-doc-card"
      className={cn(
        "max-w-[220px] flex-row items-center gap-8 rounded-12 border px-12 py-8",
        failed ? "border-status-error-05" : "border-border-01",
      )}
    >
      {processing ? (
        <ActivityIndicator size="small" />
      ) : (
        <Icon
          as={failed ? SvgAlertCircle : SvgFileText}
          size={16}
          className={failed ? "text-status-error-05" : "text-text-02"}
        />
      )}
      <View className="min-w-0 shrink">
        <Text font="main-ui-body" color="text-04" numberOfLines={1}>
          {file.name}
        </Text>
        <Text
          font="secondary-body"
          color={
            failed ? "status-error-05" : processing ? "text-03" : "text-02"
          }
          numberOfLines={1}
        >
          {attachmentStatusLabel(file, progress)}
        </Text>
      </View>
      {canRemove ? (
        <Pressable
          onPress={() => onRemove(file.id)}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel={`Remove ${file.name}`}
        >
          <Icon as={SvgX} size={16} className="text-text-03" />
        </Pressable>
      ) : null}
    </View>
  );
});
