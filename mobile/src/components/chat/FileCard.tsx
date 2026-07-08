import { ActivityIndicator, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import {
  isProcessingStatus,
  UserFileStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { extensionOf } from "@/lib/files";
import SvgFileText from "@/icons/file-text";
import SvgX from "@/icons/x";

interface FileCardProps {
  file: ProjectFile;
  onRemove?: () => void;
  progress?: number; // 0..1 while UPLOADING
}

function statusLabel(file: ProjectFile, progress?: number): string {
  switch (String(file.status).toUpperCase()) {
    case UserFileStatus.UPLOADING:
      return progress != null
        ? `Uploading… ${Math.round(progress * 100)}%`
        : "Uploading…";
    case UserFileStatus.PROCESSING:
      return "Processing…";
    case UserFileStatus.INDEXING:
      return "Indexing…";
    case UserFileStatus.DELETING:
      return "Deleting…";
    case UserFileStatus.FAILED:
      return "Failed";
    default:
      // web leaves this blank; "File" avoids a lone filename
      return extensionOf(file.name) || "File";
  }
}

// Image thumbnails are deferred to PR 8 (auth-image bearer).
export function FileCard({ file, onRemove, progress }: FileCardProps) {
  const processing = isProcessingStatus(file.status);
  const deleting =
    String(file.status).toUpperCase() === UserFileStatus.DELETING;
  const canRemove = onRemove != null && !processing && !deleting;

  return (
    <View className="flex-row items-center gap-8 rounded-12 border border-border-01 px-12 py-8">
      {processing ? (
        <ActivityIndicator size="small" />
      ) : (
        <Icon as={SvgFileText} size={16} className="text-text-02" />
      )}
      <View className="min-w-0 flex-1">
        <Text font="main-ui-body" color="text-04" numberOfLines={1}>
          {file.name}
        </Text>
        <Text
          font="secondary-body"
          color={processing ? "text-03" : "text-02"}
          numberOfLines={1}
        >
          {statusLabel(file, progress)}
        </Text>
      </View>
      {canRemove ? (
        <Button
          icon={SvgX}
          prominence="tertiary"
          size="sm"
          accessibilityLabel={`Remove ${file.name}`}
          onPress={onRemove}
        />
      ) : null}
    </View>
  );
}
