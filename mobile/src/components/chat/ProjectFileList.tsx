import { memo } from "react";
import { Pressable, View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import {
  isProcessingStatus,
  UserFileStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { extensionOf, isFailedFile, isImageName } from "@/lib/files";
import { cn } from "@/lib/utils";
import SvgAlertCircle from "@/icons/alert-circle";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgX from "@/icons/x";

interface ProjectFileListProps {
  files: ProjectFile[];
  onRemove: (id: string) => void;
}

// Vertical document-list shape, deliberately distinct from the composer's chip-style FileCard.
export function ProjectFileList({ files, onRemove }: ProjectFileListProps) {
  return (
    <View className="overflow-hidden rounded-12 border border-border-01">
      {files.map((file, index) => (
        <View key={file.id}>
          {index > 0 ? <Separator /> : null}
          <ProjectFileRow file={file} onRemove={onRemove} />
        </View>
      ))}
    </View>
  );
}

const ProjectFileRow = memo(function ProjectFileRow({
  file,
  onRemove,
}: {
  file: ProjectFile;
  onRemove: (id: string) => void;
}) {
  const failed = isFailedFile(file);
  const uploading =
    String(file.status).toUpperCase() === UserFileStatus.UPLOADING;
  const processing = isProcessingStatus(file.status);
  const label = failed
    ? "Upload failed"
    : uploading
      ? "Uploading…"
      : processing
        ? "Processing…"
        : extensionOf(file.name).toUpperCase() || "File";

  return (
    <View className="flex-row items-center gap-12 px-12 py-8">
      <View
        style={{ width: 36, height: 36 }}
        className={cn(
          "items-center justify-center rounded-08",
          failed ? "bg-status-error-01" : "bg-background-tint-01",
        )}
      >
        {uploading || processing ? (
          <Spinner size={16} />
        ) : (
          <Icon
            as={
              failed
                ? SvgAlertCircle
                : isImageName(file.name)
                  ? SvgImage
                  : SvgFileText
            }
            size={16}
            className={failed ? "text-status-error-05" : "text-text-02"}
          />
        )}
      </View>

      <View className="min-w-0 flex-1">
        <Text
          font="main-ui-body"
          color={failed ? "status-error-05" : "text-04"}
          numberOfLines={1}
        >
          {file.name}
        </Text>
        <Text
          font="secondary-body"
          color={failed ? "status-error-05" : "text-02"}
          numberOfLines={1}
        >
          {label}
        </Text>
      </View>

      <Pressable
        onPress={() => onRemove(file.id)}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={`Remove ${file.name}`}
        className="p-4"
        style={({ pressed }) => (pressed ? { opacity: 0.6 } : undefined)}
      >
        <Icon as={SvgX} size={16} className="text-text-03" />
      </Pressable>
    </View>
  );
});
