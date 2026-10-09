import { memo } from "react";
import { Pressable, View } from "react-native";

import { AttachmentImage } from "@/components/chat/AttachmentImage";
import { Icon } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/spinner";
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

// Mirrors web `shadow-xs` on the remove control.
const REMOVE_SHADOW = {
  shadowColor: "#000000",
  shadowOffset: { width: 0, height: 1 },
  shadowOpacity: 0.06,
  shadowRadius: 2,
  elevation: 1,
} as const;

interface FileCardProps {
  file: ProjectFile;
  // Omit for a read-only card (a sent message's files).
  onRemove?: (id: string) => void;
}

function isImage(file: ProjectFile): boolean {
  return file.chat_file_type === ChatFileType.IMAGE || isImageName(file.name);
}

// Memoized + atomic progress selector so a store tick re-renders only this card, not the whole
// composer strip. Stays removable while INDEXING/FAILED so the user can unblock send.
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
            <Spinner size={20} />
          ) : (
            <AttachmentImage fileId={file.file_id} size={IMAGE_SIZE} />
          )}
        </View>
        {canRemove ? (
          // Web reveals this on hover; touch has no hover, so it stays visible.
          <Pressable
            onPress={() => onRemove(file.id)}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${file.name}`}
            style={[
              { top: -8, left: -8, width: 16, height: 16, zIndex: 10 },
              REMOVE_SHADOW,
            ]}
            className="absolute items-center justify-center rounded-04 border border-border-01 bg-background-neutral-inverted-01"
          >
            <Icon as={SvgX} size={12} className="text-text-inverted-03" />
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
        <Spinner size={16} />
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
