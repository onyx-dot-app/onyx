import { memo, useMemo } from "react";
import { View } from "react-native";

import { Card, Text } from "@/components/opal";
import { AttachmentTray } from "@/components/chat/AttachmentTray";
import type { AttachmentTileModel } from "@/components/chat/AttachmentTile";
import { useAuthImageHeaders } from "@/components/chat/useAuthImageHeaders";
import { authedChatImageSource } from "@/lib/chatImageSource";
import { getApiBaseUrl } from "@/lib/serverUrl";
import { isImageFile } from "@/lib/fileTypes";
import { ChatFileType, type FileDescriptor } from "@/lib/types";

export type MessageRole = "user" | "assistant";

export interface MessageRowProps {
  role: MessageRole;
  text: string;
  files?: FileDescriptor[];
}

// NativeWind scans source for static class literals at build time, so a template
// like `` `self-${align}` `` produces no style. Pick a whole pre-written string by
// role instead of interpolating fragments.
const ROW_WRAPPER_USER = "w-full px-4 py-1 items-end";
const ROW_WRAPPER_ASSISTANT = "w-full px-4 py-1 items-start";

// User bubble mirrors web HumanMessage: sets all four corners, border-0, and
// padding explicitly so they override the Card base regardless of merge order.
const BUBBLE_USER =
  "max-w-[85%] bg-background-tint-02 border-0 rounded-tl-[16px] rounded-tr-[16px] rounded-bl-[16px] rounded-br-[0px] px-3 py-2";
const BUBBLE_ASSISTANT = "max-w-[85%] bg-background-neutral-01 border-border-02";

function MessageRowComponent({ role, text, files }: MessageRowProps) {
  const isUser = role === "user";
  const wrapperClass = isUser ? ROW_WRAPPER_USER : ROW_WRAPPER_ASSISTANT;
  const bubbleClass = isUser ? BUBBLE_USER : BUBBLE_ASSISTANT;

  // Sent-message images load from the authed backend route (web rides cookies).
  const headers = useAuthImageHeaders();
  const tiles = useMemo<AttachmentTileModel[]>(() => {
    if (!files || files.length === 0) return [];
    return files.map((file) => {
      const isImage =
        file.type === ChatFileType.IMAGE || isImageFile(file.name ?? "");
      return {
        id: file.id,
        name: file.name ?? "file",
        isImage,
        status: "uploaded" as const,
        // Wait for the bearer header before loading the authed /chat/file URL so
        // we don't fire a guaranteed-401 request on first paint.
        imageSource: isImage
          ? authedChatImageSource(getApiBaseUrl(), file.id, headers)
          : undefined,
      };
    });
  }, [files, headers]);

  return (
    <View className={wrapperClass}>
      {tiles.length > 0 ? <AttachmentTray models={tiles} /> : null}
      {text ? (
        <Card className={bubbleClass}>
          <Text font="main-content-body" color="text-05">
            {text}
          </Text>
        </Card>
      ) : null}
    </View>
  );
}

const MessageRow = memo(MessageRowComponent);
MessageRow.displayName = "MessageRow";

export { MessageRow };
