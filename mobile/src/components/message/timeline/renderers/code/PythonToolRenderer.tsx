// PythonToolRenderer.tsx — the code-interpreter (Python) tool block. Native mirror of web PythonToolRenderer.
//
// Reduces PythonToolPackets to {code, stdout, stderr, fileIds, isStreaming,
// isExecuting, isComplete, hasError}.
//
// AMENDMENTS vs web:
//   - Syntax highlighting (highlight.js) is OUT OF SCOPE; CodeBlock renders flat
//     monospace (matches the rest of the mobile port).
//   - COMPACT caps the body at maxHeight 96 with overflow hidden instead of the
//     web FadingEdgeContainer (no fade-mask primitive on RN yet).

import { useEffect, useMemo } from "react";
import { View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
  withDelay,
  Easing,
} from "react-native-reanimated";

import {
  PacketType,
  CODE_INTERPRETER_TOOL_TYPES,
  type PythonToolPacket,
  type PythonToolStart,
  type PythonToolDelta,
  type ToolCallArgumentDelta,
} from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
} from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { CodeBlock } from "@/components/markdown/CodeBlock";
import { SvgTerminal } from "@/components/icons";
import { useToken } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

// ---------------------------------------------------------------------------
// State reduction
// ---------------------------------------------------------------------------

interface PythonState {
  code: string;
  stdout: string;
  stderr: string;
  fileIds: string[];
  isStreaming: boolean;
  isExecuting: boolean;
  isComplete: boolean;
  hasError: boolean;
}

// Faithful port of web `constructCurrentPythonState`.
function constructCurrentPythonState(packets: PythonToolPacket[]): PythonState {
  // Accumulate streaming code from argument deltas (arrives before PythonToolStart).
  const streamingCode = packets
    .filter(
      (packet) =>
        packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        (packet.obj as ToolCallArgumentDelta).tool_type ===
          CODE_INTERPRETER_TOOL_TYPES.PYTHON
    )
    .map((packet) =>
      String((packet.obj as ToolCallArgumentDelta).argument_deltas.code ?? "")
    )
    .join("");

  const pythonStart =
    (packets.find((packet) => packet.obj.type === PacketType.PYTHON_TOOL_START)
      ?.obj as PythonToolStart | undefined) ?? null;

  const pythonDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.PYTHON_TOOL_DELTA)
    .map((packet) => packet.obj as PythonToolDelta);

  const pythonEnd =
    packets.find(
      (packet) =>
        packet.obj.type === PacketType.SECTION_END ||
        packet.obj.type === PacketType.ERROR
    )?.obj ?? null;

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
  const isExecuting = Boolean(pythonStart) && !pythonEnd;
  const isComplete = Boolean(pythonStart) && Boolean(pythonEnd);
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

// ---------------------------------------------------------------------------
// Loading indicator (3-dot pulse)
// ---------------------------------------------------------------------------

interface PulseDotProps {
  delay: number;
  color: string;
}

// Mirrors web's `animate-pulse` (~1s ease-in-out alternating), staggered per dot.
function PulseDot({ delay, color }: PulseDotProps) {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withDelay(
      delay,
      withRepeat(
        withSequence(
          withTiming(0.35, {
            duration: 500,
            easing: Easing.inOut(Easing.ease),
          }),
          withTiming(1, { duration: 500, easing: Easing.inOut(Easing.ease) })
        ),
        -1,
        false
      )
    );
  }, [opacity, delay]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[
        {
          width: 4,
          height: 4,
          borderRadius: radii["full"],
          backgroundColor: color,
        },
        animatedStyle,
      ]}
    />
  );
}

interface LoadingIndicatorProps {
  label: string;
}

function LoadingIndicator({ label }: LoadingIndicatorProps) {
  const dotColor = useToken("text-03");
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <View style={{ flexDirection: "row", gap: 2 }}>
        <PulseDot delay={0} color={dotColor} />
        <PulseDot delay={100} color={dotColor} />
        <PulseDot delay={200} color={dotColor} />
      </View>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

const COMPACT_MAX_HEIGHT = 96;

export function PythonToolRenderer({
  packets,
  onComplete,
  renderType,
  children,
}: MessageRendererProps<PythonToolPacket>) {
  const {
    code,
    stdout,
    stderr,
    fileIds,
    isStreaming,
    isExecuting,
    isComplete,
    hasError,
  } = useMemo(() => constructCurrentPythonState(packets), [packets]);

  useFireOnComplete(isComplete, onComplete);

  const status = useMemo(() => {
    if (isStreaming) return "Writing code...";
    if (isExecuting) return "Executing Python code...";
    if (hasError) return "Python execution failed";
    if (isComplete) return "Python execution completed";
    return "Python execution";
  }, [isStreaming, isExecuting, isComplete, hasError]);

  // Resolve surface tokens for the output/error boxes.
  const stdoutBg = useToken("background-neutral-02");
  const stderrBg = useToken("status-error-01");
  const stderrBorder = useToken("status-error-02");

  const content = (
    <View style={{ gap: 8 }}>
      {/* Loading indicator while streaming or executing. */}
      {(isStreaming || isExecuting) && (
        <LoadingIndicator
          label={isStreaming ? "Writing code..." : "Running code..."}
        />
      )}

      {/* Code block. */}
      {code.length > 0 && (
        <CodeBlock code={code.trim()} language="python" />
      )}

      {/* stdout. */}
      {stdout.length > 0 && (
        <View
          style={{
            backgroundColor: stdoutBg,
            borderRadius: radii["08"],
            padding: 12,
          }}
        >
          <Text
            font="secondary-action"
            color="text-03"
            style={{ marginBottom: 4 }}
          >
            Output:
          </Text>
          <Text font="secondary-mono" color="text-01">
            {stdout}
          </Text>
        </View>
      )}

      {/* stderr. */}
      {stderr.length > 0 && (
        <View
          style={{
            backgroundColor: stderrBg,
            borderColor: stderrBorder,
            borderWidth: 1,
            borderRadius: radii["08"],
            padding: 12,
          }}
        >
          <Text
            font="secondary-action"
            color="status-error-05"
            style={{ marginBottom: 4 }}
          >
            Error:
          </Text>
          <Text font="secondary-mono" color="status-error-05">
            {stderr}
          </Text>
        </View>
      )}

      {/* Generated file count. */}
      {fileIds.length > 0 && (
        <Text font="secondary-body" color="text-03">
          {`Generated ${fileIds.length} file${
            fileIds.length !== 1 ? "s" : ""
          }`}
        </Text>
      )}

      {/* No-output fallback — only when complete with no output. */}
      {isComplete && stdout.length === 0 && stderr.length === 0 && (
        <View style={{ alignItems: "center", paddingVertical: 8, gap: 4 }}>
          <View style={{ opacity: 0.5 }}>
            <SvgTerminal size={16} color="text-04" />
          </View>
          <Text font="secondary-body" color="text-04">
            No output
          </Text>
        </View>
      )}
    </View>
  );

  // COMPACT caps the body height (web uses a FadingEdgeContainer max-h-24).
  const body =
    renderType === RenderType.COMPACT ? (
      <View style={{ maxHeight: COMPACT_MAX_HEIGHT, overflow: "hidden" }}>
        {content}
      </View>
    ) : (
      content
    );

  return children([
    {
      icon: "terminal",
      status,
      content: body,
      supportsCollapsible: true,
      alwaysCollapsible: true,
    },
  ]);
}

export default PythonToolRenderer;
