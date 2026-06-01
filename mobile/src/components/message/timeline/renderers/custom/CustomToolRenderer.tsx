// CustomToolRenderer.tsx — renders a user-defined ("custom") tool call.
// Ported from web:
//   web/src/app/app/message/messageComponents/renderers/CustomToolRenderer.tsx
//
// Scans CUSTOM_TOOL_START / CUSTOM_TOOL_ARGS / CUSTOM_TOOL_DELTA + SECTION_END /
// ERROR packets into {toolName, args, responseType, data, fileIds, error,
// isRunning, isComplete}, then renders:
//   - a "Waiting for response..." line while still running,
//   - an IoBlockLabel "Request" + a CodeBlock of the JSON-stringified args,
//   - an error message (when the tool errored),
//   - file responses as Open/Download links (opened via Linking),
//   - an IoBlockLabel "Response" + a CodeBlock of the JSON/text data.
//
// DEVIATIONS from web:
//   - No syntax highlighting (web used highlight.js); CodeBlock renders flat
//     monospace text, matching the mobile CodeBlock contract.
//   - COMPACT drops the web FadingEdgeContainer (max-h clip + fade); it renders
//     the same content as FULL, per the mobile port brief.
//   - The image/file URL is built with `chatFileUrl(appConfig.apiBaseUrl, …)`,
//     the mobile equivalent of web `buildImgUrl`.

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
import { appConfig } from "@/lib/config";
import { useToken } from "@/theme/ThemeProvider";
import { timelineTokens as T } from "@/theme/timelineTokens";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

// ---------------------------------------------------------------------------
// State reduction
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// File link (Open / Download)
// ---------------------------------------------------------------------------

interface FileLinkProps {
  fileId: string;
  index: number;
  linkColor: string;
}

function FileLink({ fileId, index, linkColor }: FileLinkProps) {
  const url = useMemo(
    () => chatFileUrl(appConfig.apiBaseUrl, fileId),
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

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

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

  // Header/status label — mirrors the web status logic.
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
      {/* Loading indicator — only before any response has arrived. */}
      {isRunning && !error && !fileIds && !hasData && (
        <Text font="secondary-body" color="text-03">
          Waiting for response...
        </Text>
      )}

      {/* Tool arguments. */}
      {argsJson && (
        <View style={{ gap: 4 }}>
          <IoBlockLabel label="Request" />
          <CodeBlock code={argsJson} language="json" />
        </View>
      )}

      {/* Error display. */}
      {error && (
        <View style={{ paddingLeft: T.timelineCommonTextPadding }}>
          <Text font="main-ui-muted" color="text-03">
            {error.message}
          </Text>
        </View>
      )}

      {/* File responses. */}
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

      {/* JSON / text responses. */}
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

  // Auth error: always render with the error surface, non-collapsible.
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

  // FULL mode — collapsible, no right padding.
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

  // COMPACT (and any other) mode — same content (web wrapped this in a fading
  // edge container; the mobile port renders the content directly).
  const result: RendererResult = {
    icon: "terminal",
    status,
    supportsCollapsible: true,
    content,
  };
  return children([result]);
}

export default CustomToolRenderer;
