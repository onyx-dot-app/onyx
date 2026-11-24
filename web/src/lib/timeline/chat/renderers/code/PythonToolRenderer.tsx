import { useEffect } from "react";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import { useTranslations } from "next-intl";
import {
  PacketType,
  PythonToolPacket,
  PythonToolStart,
  PythonToolDelta,
  ToolCallArgumentDelta,
  SectionEnd,
  isCodeInterpreterToolType,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { ShadowDiv } from "@opal/components";

// Helper function to construct current Python execution state
function constructCurrentPythonState(packets: PythonToolPacket[]) {
  // Accumulate streaming code from argument deltas (arrives before PythonToolStart)
  const streamingCode = packets
    .filter(
      (packet) =>
        packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        isCodeInterpreterToolType(
          (packet.obj as ToolCallArgumentDelta).tool_type
        )
    )
    .map((packet) =>
      String((packet.obj as ToolCallArgumentDelta).argument_deltas.code ?? "")
    )
    .join("");
  const pythonStart = packets.find(
    (packet) => packet.obj.type === PacketType.PYTHON_TOOL_START
  )?.obj as PythonToolStart | null;
  const pythonDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.PYTHON_TOOL_DELTA)
    .map((packet) => packet.obj as PythonToolDelta);
  const pythonEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  )?.obj as SectionEnd | null;

  // Use complete code from PythonToolStart if available, else use streamed code.
  const code = pythonStart?.code || streamingCode;
  const stdout = pythonDeltas
    .map((delta) => delta?.stdout || "")
    .filter((s) => s)
    .join("");
  const stderr = pythonDeltas
    .map((delta) => delta?.stderr || "")
    .filter((s) => s)
    .join("");
  const fileIds = pythonDeltas.flatMap((delta) => delta?.file_ids || []);
  const isStreaming = !pythonStart && streamingCode.length > 0;
  const isExecuting = pythonStart && !pythonEnd;
  const isComplete = pythonStart && pythonEnd;
  const hasError = stderr.length > 0;

  return {
    code,
    stdout,
    stderr,
    fileIds,
    isStreaming,
    isExecuting,
    isComplete,
    hasError,
  };
}

export const PythonToolRenderer: MessageRenderer<PythonToolPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const {
    code,
    stdout,
    stderr,
    fileIds,
    isStreaming,
    isExecuting,
    isComplete,
  } = constructCurrentPythonState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = t("python.running.status");
  const doneStatus = t("python.ran.status");

  // Nothing to open until the code starts streaming in.
  const hasBody = code.trim().length > 0 || !!stdout || !!stderr || isComplete;

  // Shared content for all states - used by both FULL and compact modes
  const content = (
    <div className="flex flex-col space-y-2">
      {/* Loading indicator when streaming or executing */}
      {(isStreaming || isExecuting) && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <div className="flex gap-0.5">
            <div className="w-1 h-1 bg-current rounded-full animate-pulse"></div>
            <div
              className="w-1 h-1 bg-current rounded-full animate-pulse"
              style={{ animationDelay: "0.1s" }}
            ></div>
            <div
              className="w-1 h-1 bg-current rounded-full animate-pulse"
              style={{ animationDelay: "0.2s" }}
            ></div>
          </div>
          <span>
            {isStreaming
              ? t("python.writingCode.status")
              : t("python.runningCode.label")}
          </span>
        </div>
      )}

      <CommandBody
        command={code.trim()}
        language="python"
        output={
          isComplete && !stdout && !stderr ? t("python.noOutput.text") : stdout
        }
        error={stderr}
        // A finished run already carries its no-output text; before then,
        // empty means the code is still being written.
        emptyLabel=""
      />

      {/* File count */}
      {fileIds.length > 0 && (
        <div className="text-sm text-text-03">
          {t("python.generatedFiles.label", { count: fileIds.length })}
        </div>
      )}
    </div>
  );

  // FULL mode: render content directly
  if (renderType === RenderType.FULL) {
    return children([
      {
        icon: STEP_ICONS.execute,
        status,
        doneStatus,
        content: hasBody ? content : null,
        supportsCollapsible: true,
        alwaysCollapsible: true,
      },
    ]);
  }

  // Compact mode: wrap content in FadeDiv
  return children([
    {
      icon: STEP_ICONS.execute,
      status,
      doneStatus,
      supportsCollapsible: true,
      alwaysCollapsible: true,
      content: hasBody ? (
        <ShadowDiv
          shadowDirection="bottom-only"
          variant="mask"
          shadowHeight={8}
          className="max-h-24 overflow-hidden"
        >
          {content}
        </ShadowDiv>
      ) : null,
    },
  ]);
};
