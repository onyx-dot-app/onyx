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
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/lib/timeline/chat/message/messageComponents/types";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { Button, CodePanel, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { downloadFile } from "@/lib/download";
import { openExternalLink } from "@/lib/search/utils";
import { SvgDownload, SvgExternalLink } from "@opal/icons";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { codeSpan, markdown } from "@opal/utils";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";
import {
  flatFields,
  isEcho,
  isEmptyPayload,
  type ToolField,
} from "@/lib/timeline/chat/toolPayload";

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

interface ToolFieldsProps {
  fields: ToolField[];
}

function ToolFields({ fields }: ToolFieldsProps) {
  return (
    <Section alignItems="stretch" gap={1} height="fit">
      {fields.map(([key, value]) => (
        <Section
          key={key}
          flexDirection="row"
          justifyContent="start"
          alignItems="start"
          gap={2}
          height="fit"
        >
          <Text font="secondary-mono" color="text-03" wordWrap="wrap-anywhere">
            <span className="whitespace-pre-wrap">{`${key}:`}</span>
          </Text>
          <Text font="secondary-mono" color="text-04" wordWrap="wrap-anywhere">
            <span className="whitespace-pre-wrap">{String(value)}</span>
          </Text>
        </Section>
      ))}
    </Section>
  );
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

  // A stopped step keeps the running title; a done or failed one says how it
  // ended, the tool's own errors included. The tool's name is a code span.
  const status = markdown(
    t("customTool.runningStatus.text", { toolName: codeSpan(toolName) })
  );
  const doneStatus = useMemo(() => {
    if (!isComplete) return null;
    const chip = codeSpan(toolName);
    if (error) {
      if (error.is_unreachable)
        return markdown(
          t("customTool.unreachableStatus.text", { toolName: chip })
        );
      if (error.status_code === null)
        return markdown(t("customTool.blockedStatus.text", { toolName: chip }));
      return markdown(
        error.is_auth_error
          ? t("customTool.authFailedStatus.text", {
              toolName: chip,
              statusCode: error.status_code,
            })
          : t("customTool.failedStatus.text", {
              toolName: chip,
              statusCode: error.status_code,
            })
      );
    }
    if (responseType === "image")
      return markdown(t("customTool.imagesStatus.text", { toolName: chip }));
    if (responseType === "csv")
      return markdown(t("customTool.fileStatus.text", { toolName: chip }));
    return markdown(t("customTool.completedStatus.text", { toolName: chip }));
  }, [toolName, responseType, error, isComplete, t]);

  const icon = STEP_ICONS.tool;

  const toolArgsJson = useMemo(
    () => (toolArgs ? JSON.stringify(toolArgs, null, 2) : ""),
    [toolArgs]
  );
  const dataJson = useMemo(
    () =>
      data !== undefined && data !== null && typeof data === "object"
        ? JSON.stringify(data, null, 2)
        : null,
    [data]
  );
  const hasFiles = !error && !!fileIds && fileIds.length > 0;
  const argFields = useMemo(() => flatFields(toolArgs), [toolArgs]);
  const dataFields = useMemo(() => flatFields(data), [data]);
  const showArgs = !isEmptyPayload(toolArgs);
  // A response that only repeats the arguments adds nothing.
  const hasResult =
    !isEmptyPayload(data) || (data !== null && typeof data === "object");
  const showData = hasResult && !isEcho(dataFields, argFields);
  // The response shows once it arrives, and as "waiting" while the tool runs.
  const showResponse = !!error || hasFiles || showData || isRunning;
  const argsLines = useCodeLines(toolArgsJson, "json");
  const dataLines = useCodeLines(dataJson ?? "", "json");

  const content = useMemo(
    () =>
      // One panel: the request, then the response (waiting, files, JSON,
      // text or the tool's error), each under its own title row. Nothing to
      // open until the request or a response arrives.
      showArgs || error || hasFiles || showData ? (
        <CodePanel>
          {showArgs && (
            <>
              <CodePanel.Header
                title={t("customTool.requestBlock.label")}
                copyText={toolArgsJson}
              />
              {argFields ? (
                <CodePanel.Content>
                  <ToolFields fields={argFields} />
                </CodePanel.Content>
              ) : (
                <CodePanel.Lines lineNumbers lines={argsLines} />
              )}
            </>
          )}
          {showResponse && (
            <>
              <CodePanel.Header
                title={t("customTool.responseBlock.label")}
                copyText={
                  error || hasFiles || !showData
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
              ) : showData ? (
                dataFields ? (
                  <CodePanel.Content>
                    <ToolFields fields={dataFields} />
                  </CodePanel.Content>
                ) : dataJson ? (
                  <CodePanel.Lines lineNumbers lines={dataLines} />
                ) : (
                  <CodePanel.Output>{String(data)}</CodePanel.Output>
                )
              ) : (
                // The response is still awaited.
                <CodePanel.Output loading />
              )}
            </>
          )}
        </CodePanel>
      ) : null,
    [
      showArgs,
      argFields,
      dataFields,
      showData,
      toolArgsJson,
      dataJson,
      argsLines,
      dataLines,
      showResponse,
      hasFiles,
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
      content: content && (
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
