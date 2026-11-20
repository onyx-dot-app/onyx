import { Section } from "@opal/layouts";
import { FileBody } from "@/lib/timeline/components/bodies/FileBody";
import { useEffect } from "react";
import { codeSpan, markdown } from "@opal/utils";
import { useTranslations } from "next-intl";
import { STEP_ICONS } from "@/lib/timeline/icons";
import {
  PacketType,
  FileReaderToolPacket,
  FileReaderResult,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";

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
  // The file preview shares Craft's read-step labels.
  const tRead = useTranslations("craft.toolCards.read");
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

  const statusText = t("fileReader.reading.status");
  // The file name reads as code.
  const doneStatusText = state.fileName
    ? markdown(
        t("fileReader.read.status", {
          fileName: codeSpan(state.fileName),
          ...charRange,
        })
      )
    : statusText;

  const isCompact = renderType === RenderType.COMPACT;

  if (isCompact) {
    return children([
      {
        icon: STEP_ICONS.read,
        status: statusText,
        doneStatus: doneStatusText,
        supportsCollapsible: true,
        timelineLayout: "timeline",
        content: <></>,
      },
    ]);
  }

  const hasPreview = state.previewStart || state.previewEnd;

  return children([
    {
      icon: STEP_ICONS.read,
      status: statusText,
      doneStatus: doneStatusText,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <Section gap={1} alignItems="start" height="fit">
          {state.fileName ? (
            <>
              {/* The panel's title row names the file; the step's title
                  gives the character range. */}
              {hasPreview && (
                <FileBody
                  content={
                    state.previewEnd
                      ? `${state.previewStart}\n\u2026\n${state.previewEnd}`
                      : state.previewStart
                  }
                  path={state.fileName}
                  emptyLabel={tRead("emptyFile.label")}
                  moreLinesLabel={(count) =>
                    tRead("moreLines.label", { count })
                  }
                  showAllLabel={tRead("showAll.button")}
                  excerpt
                />
              )}
            </>
          ) : null}
        </Section>
      ),
    },
  ]);
};
