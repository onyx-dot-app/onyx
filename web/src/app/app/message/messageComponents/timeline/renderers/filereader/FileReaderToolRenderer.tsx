import { useEffect } from "react";
import { SvgFileText } from "@opal/icons";
import {
  PacketType,
  FileReaderToolPacket,
  FileReaderResult,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/app/message/BlinkingDot";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";

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
  const result = packets.find(
    (p) => p.obj.type === PacketType.FILE_READER_RESULT
  )?.obj as FileReaderResult | null;

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
  return `chars ${startChar.toLocaleString()}\u2013${endChar.toLocaleString()} of ${totalChars.toLocaleString()}`;
}

export const FileReaderToolRenderer: MessageRenderer<
  FileReaderToolPacket,
  {}
> = ({ packets, onComplete, stopPacketSeen, renderType, children }) => {
  const state = constructFileReaderState(packets);

  useEffect(() => {
    if (state.isComplete) {
      onComplete();
    }
  }, [state.isComplete, onComplete]);

  const statusText = state.fileName
    ? `Read ${state.fileName} (${formatCharRange(
        state.startChar,
        state.endChar,
        state.totalChars
      )})`
    : "Reading file";

  const isCompact = renderType === RenderType.COMPACT;

  if (isCompact) {
    return children([
      {
        icon: SvgFileText,
        status: statusText,
        supportsCollapsible: true,
        timelineLayout: "timeline",
        content: <></>,
      },
    ]);
  }

  const hasPreview = state.previewStart || state.previewEnd;

  return children([
    {
      icon: SvgFileText,
      status: statusText,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <Section gap={0.5} alignItems="start" height="fit">
          {state.fileName ? (
            <>
              <Section
                flexDirection="row"
                alignItems="center"
                justifyContent="start"
                gap={0.5}
                height="fit"
              >
                <Text as="span" mainUiAction text02>
                  {state.fileName}
                </Text>
                <Text as="span" mainUiMuted text04>
                  {formatCharRange(
                    state.startChar,
                    state.endChar,
                    state.totalChars
                  )}
                </Text>
              </Section>
              {hasPreview && (
                <Card variant="secondary" padding={0.5} gap={0.25}>
                  <Text as="span" secondaryMono text04>
                    {state.previewStart}
                    {state.previewEnd && "\u2026"}
                  </Text>
                  {state.previewEnd && (
                    <Text as="span" secondaryMono text04>
                      {"\u2026"}
                      {state.previewEnd}
                    </Text>
                  )}
                </Card>
              )}
            </>
          ) : (
            !stopPacketSeen && <BlinkingDot />
          )}
        </Section>
      ),
    },
  ]);
};
