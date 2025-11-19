import React, { useEffect, useMemo } from "react";
import { FiExternalLink, FiDownload, FiTool } from "react-icons/fi";
import {
  PacketType,
  CustomToolPacket,
  CustomToolStart,
  CustomToolDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { buildImgUrl } from "../../../components/files/images/utils";

function constructCustomToolState(packets: CustomToolPacket[]) {
  const toolStart = packets.find(
    (p) => p.obj.type === PacketType.CUSTOM_TOOL_START
  )?.obj as CustomToolStart | null;
  const toolDeltas = packets
    .filter((p) => p.obj.type === PacketType.CUSTOM_TOOL_DELTA)
    .map((p) => p.obj as CustomToolDelta);
  const toolEnd = packets.find((p) => p.obj.type === PacketType.SECTION_END)
    ?.obj as SectionEnd | null;

  const toolName = toolStart?.tool_name || toolDeltas[0]?.tool_name || "Tool";
  const latestDelta = toolDeltas[toolDeltas.length - 1] || null;
  const responseType = latestDelta?.response_type || null;
  const data = latestDelta?.data;
  const fileIds = latestDelta?.file_ids || null;

  const isRunning = Boolean(toolStart && !toolEnd);
  const isComplete = Boolean(toolStart && toolEnd);

  return {
    toolName,
    responseType,
    data,
    fileIds,
    isRunning,
    isComplete,
  };
}

export const CustomToolRenderer: MessageRenderer<CustomToolPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  children,
}) => {
  const { toolName, responseType, data, fileIds, isRunning, isComplete } =
    constructCustomToolState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = useMemo(() => {
    if (isComplete) {
      if (responseType === "image") return `${toolName} returned images`;
      if (responseType === "csv") return `${toolName} returned a file`;
      return `${toolName} completed`;
    }
    if (isRunning) return `${toolName} running...`;
    return null;
  }, [toolName, responseType, isComplete, isRunning]);

  const icon = FiTool;

  if (renderType === RenderType.HIGHLIGHT) {
    return children({
      icon,
      status: status,
      content: (
        <div className="text-sm text-muted-foreground">
          {isRunning && `${toolName} running...`}
          {isComplete && `${toolName} completed`}
        </div>
      ),
    });
  }

  return children({
    icon,
    status,
    content: (
      <div className="flex flex-col gap-3">
        {/* File responses */}
        {fileIds && fileIds.length > 0 && (
          <div className="text-sm text-muted-foreground flex flex-col gap-2">
            {fileIds.map((fid, idx) => (
              <div key={fid} className="flex items-center gap-2 flex-wrap">
                <span className="whitespace-nowrap">File {idx + 1}</span>
                <a
                  href={buildImgUrl(fid)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline whitespace-nowrap"
                >
                  <FiExternalLink className="w-3 h-3" /> Open
                </a>
                <a
                  href={buildImgUrl(fid)}
                  download
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline whitespace-nowrap"
                >
                  <FiDownload className="w-3 h-3" /> Download
                </a>
              </div>
            ))}
          </div>
        )}

        {/* JSON/Text responses */}
        {data !== undefined && data !== null && (
          <div className="text-xs bg-gray-50 dark:bg-gray-800 p-3 rounded border max-h-96 overflow-y-auto font-mono whitespace-pre-wrap break-all">
            {typeof data === "string" ? data : JSON.stringify(data, null, 2)}
          </div>
        )}

        {/* Show placeholder if no response data yet */}
        {!fileIds && (data === undefined || data === null) && isRunning && (
          <div className="text-xs text-gray-500 italic">
            Waiting for response...
          </div>
        )}
      </div>
    ),
  });
};

export default CustomToolRenderer;
