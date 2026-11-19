import React, { useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import {
  PacketType,
  CustomToolPacket,
  CustomToolStart,
  CustomToolArgs,
  CustomToolDelta,
  CustomToolErrorInfo,
  SectionEnd,
} from "../../../services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { buildImgUrl } from "../../../components/files/images/utils";
import { Button, CodePanel, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { downloadFile } from "@/lib/download";
import { openExternalLink } from "@/lib/search/utils";
import { SvgDownload, SvgExternalLink } from "@opal/icons";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";

function constructCustomToolState(
  packets: CustomToolPacket[],
  fallbackToolName: string
) {
  const toolStart = packets.find(
    (p) => p.obj.type === PacketType.CUSTOM_TOOL_START
  )?.obj as CustomToolStart | null;
  const toolDeltas = packets
    .filter((p) => p.obj.type === PacketType.CUSTOM_TOOL_DELTA)
    .map((p) => p.obj as CustomToolDelta);
  const toolEnd = packets.find(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  )?.obj as SectionEnd | null;

  const toolName = toolStart?.display_name || fallbackToolName;
  const toolArgsPacket = packets.find(
    (p) => p.obj.type === PacketType.CUSTOM_TOOL_ARGS
  )?.obj as CustomToolArgs | null;
  const toolArgs = toolArgsPacket?.tool_args ?? null;
  const latestDelta = toolDeltas[toolDeltas.length - 1] || null;
  const responseType = latestDelta?.response_type || null;
  const data = latestDelta?.data;
  const fileIds = latestDelta?.file_ids || null;
  const error = latestDelta?.error || null;

  const isRunning = Boolean(toolStart && !toolEnd);
  const isComplete = Boolean(toolStart && toolEnd);

  return {
    toolName,
    toolArgs,
    responseType,
    data,
    fileIds,
    error,
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
  const t = useTranslations("chat.messages");
  const {
    toolName,
    toolArgs,
    responseType,
    data,
    fileIds,
    error,
    isRunning,
    isComplete,
  } = constructCustomToolState(packets, t("customTool.fallbackName.label"));

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  // A failed or stopped step keeps the running title; a done one says how it
  // ended, the tool's own errors included.
  const status = t("customTool.runningStatus.text", { toolName });
  const doneStatus = useMemo(() => {
    if (isComplete) {
      if (error) {
        if (error.is_unreachable)
          return t("customTool.unreachableStatus.text", { toolName });
        if (error.status_code === null)
          return t("customTool.blockedStatus.text", { toolName });
        return error.is_auth_error
          ? t("customTool.authFailedStatus.text", {
              toolName,
              statusCode: error.status_code,
            })
          : t("customTool.failedStatus.text", {
              toolName,
              statusCode: error.status_code,
            });
      }
      if (responseType === "image")
        return t("customTool.imagesStatus.text", { toolName });
      if (responseType === "csv")
        return t("customTool.fileStatus.text", { toolName });
      return t("customTool.completedStatus.text", { toolName });
    }
    return null;
  }, [toolName, responseType, error, isComplete, t]);

  const icon = STEP_ICONS.tool;

  const toolArgsJson = useMemo(
    () => (toolArgs ? JSON.stringify(toolArgs, null, 2) : null),
    [toolArgs]
  );
  const dataJson = useMemo(
    () =>
      data !== undefined && data !== null && typeof data === "object"
        ? JSON.stringify(data, null, 2)
        : null,
    [data]
  );
  const hasData = data !== undefined && data !== null;
  const hasFiles = !error && !!fileIds && fileIds.length > 0;
  // The response shows once it arrives, and as "waiting" while the tool runs.
  const showResponse = !!error || hasFiles || hasData || isRunning;
  const argsLines = useCodeLines(toolArgsJson ?? "", "json");
  const dataLines = useCodeLines(dataJson ?? "", "json");

  const content = useMemo(
    () =>
      // One panel: the request, then the response (waiting, files, JSON,
      // text or the tool's error), each under its own title row.
      toolArgsJson || showResponse ? (
        <CodePanel>
          {toolArgsJson && (
            <>
              <CodePanel.Header
                title={t("customTool.requestBlock.label")}
                copyText={toolArgsJson}
              />
              <CodePanel.Lines lineNumbers lines={argsLines} />
            </>
          )}
          {showResponse && (
            <>
              <CodePanel.Header
                title={t("customTool.responseBlock.label")}
                copyText={
                  error || hasFiles || !hasData
                    ? undefined
                    : (dataJson ?? String(data))
                }
              />
              {error ? (
                <CodePanel.Output error>{error.message}</CodePanel.Output>
              ) : hasFiles ? (
                <CodePanel.Content>
                  <Section alignItems="stretch" gap={0.5} height="fit">
                    {(fileIds ?? []).map((fid, idx) => (
                      <Section
                        key={fid}
                        flexDirection="row"
                        justifyContent="start"
                        gap={2}
                        height="fit"
                      >
                        <Text
                          font="secondary-body"
                          color="text-03"
                          wordWrap="whitespace-nowrap"
                        >
                          {t("customTool.fileItem.label", { index: idx + 1 })}
                        </Text>
                        {/* Open and Download, 2px apart and 0.5rem from the label. */}
                        <Section
                          flexDirection="row"
                          width="fit"
                          height="fit"
                          gap={0.5}
                        >
                          <Button
                            prominence="secondary"
                            size="xs"
                            icon={SvgExternalLink}
                            onClick={() => openExternalLink(buildImgUrl(fid))}
                          >
                            {t("customTool.openFileLink.label")}
                          </Button>
                          <Button
                            prominence="secondary"
                            size="xs"
                            icon={SvgDownload}
                            onClick={() =>
                              downloadFile("", { url: buildImgUrl(fid) })
                            }
                          >
                            {t("customTool.downloadFileLink.label")}
                          </Button>
                        </Section>
                      </Section>
                    ))}
                  </Section>
                </CodePanel.Content>
              ) : hasData ? (
                dataJson ? (
                  <CodePanel.Lines lineNumbers lines={dataLines} />
                ) : (
                  <CodePanel.Output>{String(data)}</CodePanel.Output>
                )
              ) : (
                <CodePanel.Content>
                  <div className="flex items-center gap-2 text-sm text-text-03">
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
                    <Text font="secondary-body" color="text-03">
                      {t("customTool.waitingIndicator.text")}
                    </Text>
                  </div>
                </CodePanel.Content>
              )}
            </>
          )}
        </CodePanel>
      ) : (
        <></>
      ),
    [
      toolArgsJson,
      dataJson,
      argsLines,
      dataLines,
      showResponse,
      hasFiles,
      hasData,
      data,
      fileIds,
      error,
      isRunning,
      t,
    ]
  );

  // Blocked, unreachable, or auth error: always render FULL with error surface
  if (error && (error.status_code === null || error.is_auth_error)) {
    return children([
      {
        icon,
        status,
        doneStatus,
        supportsCollapsible: false,
        surfaceBackground: "error" as const,
        content,
      },
    ]);
  }

  // FULL mode
  if (renderType === RenderType.FULL) {
    return children([
      {
        icon,
        status,
        doneStatus,
        supportsCollapsible: true,
        content,
      },
    ]);
  }

  // COMPACT mode: wrap in fading container
  return children([
    {
      icon,
      status,
      doneStatus,
      supportsCollapsible: true,
      content: (
        <ShadowDiv
          shadowDirection="bottom-only"
          variant="mask"
          shadowHeight={8}
          className="max-h-24 overflow-hidden"
        >
          {content}
        </ShadowDiv>
      ),
    },
  ]);
};

export default CustomToolRenderer;
