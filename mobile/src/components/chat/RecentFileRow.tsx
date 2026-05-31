import { Pressable, View } from "react-native";

import { Spinner, Text } from "@/components/opal";
import { CheckIcon, FileTextIcon, ImageIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { isImageFile } from "@/lib/fileTypes";
import { UserFileStatus, type ProjectFile } from "@/lib/types";

// A single "Recent Files" row — mirror of web `FileLineItem`. Loader glyph while
// the file is still processing, else an image/file icon; the trailing slot shows
// a check when the file is already attached, otherwise its extension label.
// Shared by the attach popover (quick list) and the "All Recent Files" modal.

function fileExtensionLabel(name: string): string {
  const idx = name.lastIndexOf(".");
  if (idx <= 0 || idx === name.length - 1) return "";
  const ext = name.slice(idx + 1).toLowerCase();
  return ext === "txt" ? "PLAINTEXT" : ext.toUpperCase();
}

interface RecentFileRowProps {
  file: ProjectFile;
  attached: boolean;
  onToggle: (file: ProjectFile) => void;
}

export function RecentFileRow({ file, attached, onToggle }: RecentFileRowProps) {
  const mutedColor = useToken("text-03");
  const checkColor = useToken("action-link-05");

  const isBusy =
    file.status === UserFileStatus.PROCESSING ||
    file.status === UserFileStatus.UPLOADING ||
    file.status === UserFileStatus.DELETING;
  const isImg = isImageFile(file.name);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${attached ? "Remove" : "Attach"} ${file.name}`}
      onPress={() => onToggle(file)}
      className="flex-row items-center gap-2 rounded-[8px] px-2 py-2 active:bg-background-tint-02"
    >
      <View className="h-5 w-5 items-center justify-center">
        {isBusy ? (
          <Spinner size={16} color="text-03" />
        ) : isImg ? (
          <ImageIcon size={16} color={mutedColor} />
        ) : (
          <FileTextIcon size={16} color={mutedColor} />
        )}
      </View>
      <Text
        font="main-ui-body"
        color="text-05"
        numberOfLines={1}
        style={{ flex: 1 }}
      >
        {file.name}
      </Text>
      {attached ? (
        <CheckIcon size={16} color={checkColor} />
      ) : (
        <Text font="secondary-body" color="text-03">
          {fileExtensionLabel(file.name)}
        </Text>
      )}
    </Pressable>
  );
}
