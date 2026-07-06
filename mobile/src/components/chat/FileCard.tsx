import { ActivityIndicator, View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import SvgFileText from "@/icons/file-text";

interface FileCardProps {
  file: ProjectFile;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toUpperCase();
}

function statusLabel(file: ProjectFile): string {
  switch (String(file.status).toUpperCase()) {
    case UserFileStatus.UPLOADING:
      return "Uploading…";
    case UserFileStatus.PROCESSING:
      return "Processing…";
    case UserFileStatus.DELETING:
      return "Deleting…";
    case UserFileStatus.FAILED:
      return "Failed";
    default:
      // web leaves this blank; "File" avoids a lone filename
      return extensionOf(file.name) || "File";
  }
}

// Read-only file chip; image thumbnails/remove/add land with PR 7/8.
export function FileCard({ file }: FileCardProps) {
  const processing =
    String(file.status).toUpperCase() === UserFileStatus.UPLOADING ||
    String(file.status).toUpperCase() === UserFileStatus.PROCESSING;

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
          {statusLabel(file)}
        </Text>
      </View>
    </View>
  );
}
