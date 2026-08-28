import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Card } from "@opal/components";
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
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { Section } from "@/layouts/general-layouts";
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

export const FileReaderToolRenderer: MessageRenderer<
  FileReaderToolPacket,
  {}
> = ({ packets, onComplete, stopPacketSeen, renderType, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const state = constructFileReaderState(packets);

  useEffect(() => {
    if (state.isComplete) {
      onComplete();
    }
  }, [state.isComplete, onComplete]);

  const charRange = {
    start: state.startChar,
    end: state.endChar,
    total: state.totalChars,
  };

  const statusText = state.fileName
    ? t("fileReader.read.status", { fileName: state.fileName, ...charRange })
    : t("fileReader.reading.status");

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
        <Section gap={2} alignItems="start" height="fit">
          {state.fileName ? (
            <>
              <Section
                flexDirection="row"
                alignItems="center"
                justifyContent="start"
                gap={2}
                height="fit"
              >
                <Text as="span" mainUiAction text02>
                  {state.fileName}
                </Text>
                <Text as="span" mainUiMuted text04>
                  {t("fileReader.charRange.label", charRange)}
                </Text>
              </Section>
              {hasPreview && (
                <Card background="none" border="solid" padding={2} rounding={4}>
                  <Section alignItems="start" height="fit" gap={1}>
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
                  </Section>
                </Card>
              )}
            </>
          ) : (
            !stopPacketSeen && <BlinkingBar />
          )}
        </Section>
      ),
    },
  ]);
};
