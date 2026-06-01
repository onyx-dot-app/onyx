import { memo, useMemo } from "react";
import { View } from "react-native";

import { Card, Text } from "@/components/opal";
import { AttachmentTray } from "@/components/chat/AttachmentTray";
import type { AttachmentTileModel } from "@/components/chat/AttachmentTile";
import { useAuthImageHeaders } from "@/components/chat/useAuthImageHeaders";
import { authedChatImageSource } from "@/lib/chatImageSource";
import { appConfig } from "@/lib/config";
import { isImageFile } from "@/lib/fileTypes";
import { ChatFileType, type FileDescriptor } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant";

export interface MessageRowProps {
  /** Who authored the message — drives alignment and surface styling. */
  role: MessageRole;
  /** The message body (placeholder; the real streaming list is doc 06). */
  text: string;
  /** Attachments sent with the message (rendered as a read-only tile tray). */
  files?: FileDescriptor[];
}

// ---------------------------------------------------------------------------
// Static class strings (NativeWind discipline)
// ---------------------------------------------------------------------------
//
// CRITICAL: each of these is a fully STATIC string literal. NativeWind compiles
// classes by scanning source for static strings at build time, so a template
// literal like `` `self-${align}` `` would silently produce no style. We pick a
// whole pre-written class string by role instead of interpolating fragments.

/** Row wrapper: user messages hug the right edge, assistant the left. */
const ROW_WRAPPER_USER = "w-full px-4 py-1 items-end";
const ROW_WRAPPER_ASSISTANT = "w-full px-4 py-1 items-start";

/**
 * Bubble surface (NativeWind discipline: full static strings, merged over the
 * `Card` base via `cn`/twMerge).
 *
 * User bubble mirrors the web `HumanMessage` exactly: the `background-tint-02`
 * tint with NO border, web's asymmetric "chat-tail" radius (top + bottom-left
 * rounded, bottom-right square), and web's tighter px-3/py-2 padding. We set all
 * four corners and `border-0`/padding explicitly so they deterministically
 * override the `Card` base (rounded-12 / border / p-4) regardless of merge order.
 */
const BUBBLE_USER =
  "max-w-[85%] bg-background-tint-02 border-0 rounded-tl-[16px] rounded-tr-[16px] rounded-bl-[16px] rounded-br-[0px] px-3 py-2";
const BUBBLE_ASSISTANT = "max-w-[85%] bg-background-neutral-01 border-border-02";

// ---------------------------------------------------------------------------
// MessageRow
// ---------------------------------------------------------------------------

/**
 * Memoized FlashList row (NativeWind + virtualization discipline). Renders any
 * attached files as a read-only `AttachmentTray` above the text bubble; the
 * bubble itself is omitted for files-only messages (empty text).
 */
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
          ? authedChatImageSource(appConfig.apiBaseUrl, file.id, headers)
          : undefined,
      };
    });
  }, [files, headers]);

  return (
    <View className={wrapperClass}>
      {tiles.length > 0 ? <AttachmentTray models={tiles} /> : null}
      {text ? (
        <Card className={bubbleClass}>
          {/* Web renders both human + agent body copy with `mainContentBody`. */}
          <Text font="main-content-body" color="text-05">
            {text}
          </Text>
        </Card>
      ) : null}
    </View>
  );
}

/**
 * Memoized so cell recycling and theme re-renders don't needlessly re-render
 * rows whose props are unchanged.
 */
const MessageRow = memo(MessageRowComponent);
MessageRow.displayName = "MessageRow";

export { MessageRow };
