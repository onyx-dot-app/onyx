// FileReaderToolRenderer.tsx — the "Read <file>" timeline step. Native mirror of web FileReaderToolRenderer.
//
// Reduces FileReaderToolPackets inline to {fileName, charRange, previews,
// isReading, isComplete}. Status: "Read <name> (chars X–Y of Z)" (en-dash,
// toLocaleString) or "Reading file". COMPACT => status only, empty content.
// FULL => filename + char range header, then a bordered preview surface with
// previewStart…/…previewEnd in monospace. BlinkingBar while still loading.

import { View } from "react-native";

import {
  PacketType,
  type FileReaderToolPacket,
  type FileReaderResult,
} from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
} from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

interface FileReaderState {
  fileName: string | null;
  fileId: string | null;
  startChar: number;
  endChar: number;
  totalChars: number;
  previewStart: string;
  previewEnd: string;
  isReading: boolean;
  isComplete: boolean;
}

function constructFileReaderState(
  packets: FileReaderToolPacket[]
): FileReaderState {
  const result =
    (packets.find((p) => p.obj.type === PacketType.FILE_READER_RESULT)
      ?.obj as FileReaderResult | undefined) ?? null;

  const hasStart = packets.some(
    (p) => p.obj.type === PacketType.FILE_READER_START
  );
  const hasEnd = packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  );

  return {
    fileName: result?.file_name ?? null,
    fileId: result?.file_id ?? null,
    startChar: result?.start_char ?? 0,
    endChar: result?.end_char ?? 0,
    totalChars: result?.total_chars ?? 0,
    previewStart: result?.preview_start ?? "",
    previewEnd: result?.preview_end ?? "",
    isReading: hasStart && !hasEnd,
    isComplete: hasStart && hasEnd,
  };
}

function formatCharRange(
  startChar: number,
  endChar: number,
  totalChars: number
): string {
  return `chars ${startChar.toLocaleString()}–${endChar.toLocaleString()} of ${totalChars.toLocaleString()}`;
}

export function FileReaderToolRenderer({
  packets,
  onComplete,
  stopPacketSeen,
  renderType,
  children,
}: MessageRendererProps<FileReaderToolPacket>) {
  const state = constructFileReaderState(packets);
  const colors = useThemeColors();

  useFireOnComplete(state.isComplete, onComplete);

  const statusText = state.fileName
    ? `Read ${state.fileName} (${formatCharRange(
        state.startChar,
        state.endChar,
        state.totalChars
      )})`
    : "Reading file";

  if (renderType === RenderType.COMPACT) {
    return children([
      {
        icon: "file-text",
        status: statusText,
        supportsCollapsible: true,
        timelineLayout: "timeline",
        content: <View />,
      },
    ]);
  }

  const hasPreview = Boolean(state.previewStart || state.previewEnd);

  return children([
    {
      icon: "file-text",
      status: statusText,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <View style={{ gap: 8, alignItems: "flex-start" }}>
          {state.fileName ? (
            <>
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "flex-start",
                  flexWrap: "wrap",
                  gap: 8,
                }}
              >
                <Text font="main-ui-action" color="text-02">
                  {state.fileName}
                </Text>
                <Text font="main-ui-muted" color="text-04">
                  {formatCharRange(
                    state.startChar,
                    state.endChar,
                    state.totalChars
                  )}
                </Text>
              </View>
              {hasPreview && (
                <View
                  style={{
                    alignSelf: "stretch",
                    gap: 4,
                    padding: 8,
                    borderRadius: radii["08"],
                    backgroundColor: colors["background-tint-02"],
                    borderWidth: 1,
                    borderColor: colors["border-02"],
                  }}
                >
                  <Text font="secondary-mono" color="text-04">
                    {state.previewStart}
                    {state.previewEnd ? "…" : ""}
                  </Text>
                  {state.previewEnd ? (
                    <Text font="secondary-mono" color="text-04">
                      {"…"}
                      {state.previewEnd}
                    </Text>
                  ) : null}
                </View>
              )}
            </>
          ) : (
            !stopPacketSeen && <BlinkingBar />
          )}
        </View>
      ),
    },
  ]);
}

export default FileReaderToolRenderer;
