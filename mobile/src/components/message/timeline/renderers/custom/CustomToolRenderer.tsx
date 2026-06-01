// Native mirror of web CustomToolRenderer. No syntax highlighting; COMPACT drops
// the web FadingEdgeContainer and renders the same content as FULL.

import { useMemo } from "react";
import { Linking, Pressable, View } from "react-native";

import {
  PacketType,
  type CustomToolArgs,
  type CustomToolDelta,
  type CustomToolErrorInfo,
  type CustomToolPacket,
  type CustomToolStart,
} from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
  type RendererResult,
} from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { SvgDownload, SvgExternalLink } from "@/components/icons";
import { CodeBlock } from "@/components/markdown/CodeBlock";
import { IoBlockLabel } from "@/components/message/IoBlockLabel";
import { chatFileUrl } from "@/lib/api";
import { getApiBaseUrl } from "@/lib/serverUrl";
import { useToken } from "@/theme/ThemeProvider";
import { timelineTokens as T } from "@/theme/timelineTokens";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

interface CustomToolState {
  toolName: string;
  args: Record<string, unknown> | null;
  responseType: string | null;
  data: unknown;
  fileIds: string[] | null;
  error: CustomToolErrorInfo | null;
  isRunning: boolean;
  isComplete: boolean;
}

function constructCustomToolState(packets: CustomToolPacket[]): CustomToolState {
  const toolStart =
    (packets.find((p) => p.obj.type === PacketType.CUSTOM_TOOL_START)?.obj as
      | CustomToolStart
      | undefined) ?? null;

  const toolDeltas = packets
    .filter((p) => p.obj.type === PacketType.CUSTOM_TOOL_DELTA)
    .map((p) => p.obj as CustomToolDelta);

  const toolEnd =
    packets.find(
      (p) =>
        p.obj.type === PacketType.SECTION_END ||
        p.obj.type === PacketType.ERROR
    )?.obj ?? null;

  const toolName = toolStart?.tool_name || toolDeltas[0]?.tool_name || "Tool";

  const argsPacket =
    (packets.find((p) => p.obj.type === PacketType.CUSTOM_TOOL_ARGS)?.obj as
      | CustomToolArgs
      | undefined) ?? null;
  const args = argsPacket?.tool_args ?? null;

  const latestDelta = toolDeltas[toolDeltas.length - 1] ?? null;
  const responseType = latestDelta?.response_type ?? null;
  const data = latestDelta?.data;
  const fileIds = latestDelta?.file_ids ?? null;
  const error = latestDelta?.error ?? null;

  const isRunning = Boolean(toolStart && !toolEnd);
  const isComplete = Boolean(toolStart && toolEnd);

  return {
    toolName,
    args,
    responseType,
    data,
    fileIds,
    error,
    isRunning,
    isComplete,
  };
}

interface FileLinkProps {
  fileId: string;
  index: number;
  linkColor: string;
}

function FileLink({ fileId, index, linkColor }: FileLinkProps) {
  const url = useMemo(
    () => chatFileUrl(getApiBaseUrl(), fileId),
    [fileId]
  );

  const open = () => {
    Linking.openURL(url).catch(() => undefined);
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 8,
      }}
    >
      <Text font="secondary-body" color="text-03" numberOfLines={1}>
        {`File ${index + 1}`}
      </Text>

      <Pressable
        onPress={open}
        accessibilityRole="link"
        accessibilityLabel="Open file"
        hitSlop={6}
        style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
      >
        <SvgExternalLink size={12} color="action-link-05" />
        <Text font="secondary-action" style={{ color: linkColor }} numberOfLines={1}>
          Open
        </Text>
      </Pressable>

      <Pressable
        onPress={open}
        accessibilityRole="link"
        accessibilityLabel="Download file"
        hitSlop={6}
        style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
      >
        <SvgDownload size={12} color="action-link-05" />
        <Text font="secondary-action" style={{ color: linkColor }} numberOfLines={1}>
          Download
        </Text>
      </Pressable>
    </View>
  );
}

export function CustomToolRenderer({
  packets,
  onComplete,
  renderType,
  children,
}: MessageRendererProps<CustomToolPacket>) {
  const {
    toolName,
    args,
    responseType,
    data,
    fileIds,
    error,
    isRunning,
    isComplete,
  } = useMemo(() => constructCustomToolState(packets), [packets]);

  const linkColor = useToken("action-link-05");

  useFireOnComplete(isComplete, onComplete);

  const status = useMemo<string | null>(() => {
    if (isComplete) {
      if (error) {
        return error.is_auth_error
          ? `${toolName} authentication failed (HTTP ${error.status_code})`
          : `${toolName} failed (HTTP ${error.status_code})`;
      }
      if (responseType === "image") return `${toolName} returned images`;
      if (responseType === "csv") return `${toolName} returned a file`;
      return `${toolName} completed`;
    }
    if (isRunning) return `${toolName} running...`;
    return null;
  }, [toolName, responseType, error, isComplete, isRunning]);

  const argsJson = useMemo(
    () => (args ? JSON.stringify(args, null, 2) : null),
    [args]
  );

  const dataJson = useMemo(
    () =>
      data !== undefined && data !== null && typeof data === "object"
        ? JSON.stringify(data, null, 2)
        : null,
    [data]
  );

  const hasData = data !== undefined && data !== null;

  const content = (
    <View style={{ gap: 12 }}>
      {isRunning && !error && !fileIds && !hasData && (
        <Text font="secondary-body" color="text-03">
          Waiting for response...
        </Text>
      )}

      {argsJson && (
        <View style={{ gap: 4 }}>
          <IoBlockLabel label="Request" />
          <CodeBlock code={argsJson} language="json" />
        </View>
      )}

      {error && (
        <View style={{ paddingLeft: T.timelineCommonTextPadding }}>
          <Text font="main-ui-muted" color="text-03">
            {error.message}
          </Text>
        </View>
      )}

      {!error && fileIds && fileIds.length > 0 && (
        <View style={{ gap: 8 }}>
          {fileIds.map((fid, idx) => (
            <FileLink
              key={fid}
              fileId={fid}
              index={idx}
              linkColor={linkColor}
            />
          ))}
        </View>
      )}

      {!error && hasData && (
        <View style={{ gap: 4 }}>
          <IoBlockLabel label="Response" />
          {dataJson ? (
            <CodeBlock code={dataJson} language="json" />
          ) : (
            <CodeBlock code={String(data)} />
          )}
        </View>
      )}
    </View>
  );

  if (error?.is_auth_error) {
    const result: RendererResult = {
      icon: "terminal",
      status,
      supportsCollapsible: false,
      noPaddingRight: true,
      surfaceBackground: "error",
      content,
    };
    return children([result]);
  }

  if (renderType === RenderType.FULL) {
    const result: RendererResult = {
      icon: "terminal",
      status,
      supportsCollapsible: true,
      noPaddingRight: true,
      content,
    };
    return children([result]);
  }

  // COMPACT renders the same content (web wrapped this in a fading-edge container).
  const result: RendererResult = {
    icon: "terminal",
    status,
    supportsCollapsible: true,
    content,
  };
  return children([result]);
}

export default CustomToolRenderer;
