import React, { useEffect, useMemo } from "react";
import SvgCode from "@/icons/code";
import {
  PacketType,
  PythonToolPacket,
  PythonToolStart,
  PythonToolDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { IconProps } from "@/icons";
import { CodeBlock } from "@/app/chat/message/CodeBlock";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";

// Register Python language for highlighting
hljs.registerLanguage("python", python);

// Component to render syntax-highlighted Python code
function HighlightedPythonCode({ code }: { code: string }) {
  const highlightedHtml = useMemo(() => {
    try {
      return hljs.highlight(code, { language: "python" }).value;
    } catch {
      return code;
    }
  }, [code]);

  return (
    <span
      dangerouslySetInnerHTML={{ __html: highlightedHtml }}
      className="hljs"
    />
  );
}

// Helper function to construct current Python execution state
function constructCurrentPythonState(packets: PythonToolPacket[]) {
  const pythonStart = packets.find(
    (packet) => packet.obj.type === PacketType.PYTHON_TOOL_START
  )?.obj as PythonToolStart | null;
  const pythonDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.PYTHON_TOOL_DELTA)
    .map((packet) => packet.obj as PythonToolDelta);
  const pythonEnd = packets.find(
    (packet) => packet.obj.type === PacketType.SECTION_END
  )?.obj as SectionEnd | null;

  const code = pythonStart?.code || "";
  const stdout = pythonDeltas
    .map((delta) => delta?.stdout || "")
    .filter((s) => s)
    .join("");
  const stderr = pythonDeltas
    .map((delta) => delta?.stderr || "")
    .filter((s) => s)
    .join("");
  const fileIds = pythonDeltas.flatMap((delta) => delta?.file_ids || []);
  const isExecuting = pythonStart && !pythonEnd;
  const isComplete = pythonStart && pythonEnd;
  const hasError = stderr.length > 0;

  return {
    code,
    stdout,
    stderr,
    fileIds,
    isExecuting,
    isComplete,
    hasError,
  };
}

function CodeIcon({ size = 16, ...props }: IconProps) {
  return <SvgCode width={size} height={size} {...props} />;
}

export const PythonToolRenderer: MessageRenderer<PythonToolPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  children,
}) => {
  const { code, stdout, stderr, fileIds, isExecuting, isComplete, hasError } =
    constructCurrentPythonState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = useMemo(() => {
    if (isComplete) {
      if (hasError) {
        return "Python execution failed";
      }
      return "Python execution completed";
    }
    if (isExecuting) {
      return "Executing Python code...";
    }
    return null;
  }, [isComplete, isExecuting, hasError]);

  // Render based on renderType
  if (renderType === RenderType.FULL) {
    // Loading state - when executing
    if (isExecuting) {
      return children({
        icon: CodeIcon,
        status: "Executing Python code...",
        content: (
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
            <span>Running code...</span>
          </div>
        ),
      });
    }

    // Complete state - show output
    if (isComplete) {
      return children({
        icon: CodeIcon,
        status: hasError
          ? "Python execution failed"
          : "Python execution completed",
        content: (
          <div className="flex flex-col my-1 space-y-2">
            {code && (
              <div className="prose max-w-full">
                {/* NOTE: note that we need to trim since otherwise there's a huge 
                "space" at the start of the code block */}
                <CodeBlock className="language-python" codeText={code.trim()}>
                  <HighlightedPythonCode code={code.trim()} />
                </CodeBlock>
              </div>
            )}
            {stdout && (
              <div className="rounded-md bg-gray-100 dark:bg-gray-800 p-3">
                <div className="text-xs font-semibold mb-1 text-gray-600 dark:text-gray-400">
                  Output:
                </div>
                <pre className="text-sm whitespace-pre-wrap font-mono text-gray-900 dark:text-gray-100">
                  {stdout}
                </pre>
              </div>
            )}
            {stderr && (
              <div className="rounded-md bg-red-50 dark:bg-red-900/20 p-3 border border-red-200 dark:border-red-800">
                <div className="text-xs font-semibold mb-1 text-red-600 dark:text-red-400">
                  Error:
                </div>
                <pre className="text-sm whitespace-pre-wrap font-mono text-red-900 dark:text-red-100">
                  {stderr}
                </pre>
              </div>
            )}
            {fileIds.length > 0 && (
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Generated {fileIds.length} file{fileIds.length !== 1 ? "s" : ""}
              </div>
            )}
            {!stdout && !stderr && (
              <div className="py-2 text-center text-gray-500 dark:text-gray-400">
                <SvgCode className="w-4 h-4 mx-auto mb-1 opacity-50" />
                <p className="text-xs">No output</p>
              </div>
            )}
          </div>
        ),
      });
    }

    // Fallback
    return children({
      icon: CodeIcon,
      status: status,
      content: <div></div>,
    });
  }

  // Highlight/Short rendering
  if (isExecuting) {
    return children({
      icon: CodeIcon,
      status: "Executing Python code...",
      content: (
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
          <span>Running code...</span>
        </div>
      ),
    });
  }

  if (hasError) {
    return children({
      icon: CodeIcon,
      status: "Python execution failed",
      content: (
        <div className="text-sm text-red-600 dark:text-red-400">
          Execution failed
        </div>
      ),
    });
  }

  if (isComplete) {
    return children({
      icon: CodeIcon,
      status: "Python execution completed",
      content: (
        <div className="text-sm text-muted-foreground">
          Execution completed
          {fileIds.length > 0 &&
            ` - ${fileIds.length} file${
              fileIds.length !== 1 ? "s" : ""
            } generated`}
        </div>
      ),
    });
  }

  return children({
    icon: CodeIcon,
    status: "Python execution",
    content: (
      <div className="text-sm text-muted-foreground">Python execution</div>
    ),
  });
};
