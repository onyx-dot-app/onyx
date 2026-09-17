import { useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { ResponseItem } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import { SvgTerminal } from "@opal/icons";
import FadingEdgeContainer from "@/refresh-components/FadingEdgeContainer";
import {
  firstTool,
  isComplete as itemsComplete,
  stringArgument,
  toolMetadata,
} from "@/app/app/services/responseItems";

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

function constructCurrentPythonState(items: ResponseItem[]) {
  const tool = firstTool(items);
  const output = toolMetadata(items, "python_execution").at(-1);
  const stdout = output?.stdout ?? "";
  const stderr = output?.stderr ?? "";
  return {
    code: stringArgument(tool, "code"),
    stdout,
    stderr,
    generatedFileCount: output?.generated_files.length ?? 0,
    isStreaming: tool?.status === "pending",
    isExecuting: tool?.status === "running",
    isComplete: itemsComplete(items),
    hasError: !!output?.error || stderr.length > 0 || tool?.status === "error",
  };
}

export const PythonToolRenderer: MessageRenderer<ResponseItem, {}> = ({
  items,
  onComplete,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const {
    code,
    stdout,
    stderr,
    generatedFileCount,
    isStreaming,
    isExecuting,
    isComplete,
    hasError,
  } = constructCurrentPythonState(items);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = useMemo(() => {
    if (isStreaming) {
      return t("python.writingCode.status");
    }
    if (isExecuting) {
      return t("python.executing.status");
    }
    if (hasError) {
      return t("python.failed.status");
    }
    if (isComplete) {
      return t("python.completed.status");
    }
    return t("python.default.status");
  }, [isStreaming, isComplete, isExecuting, hasError, t]);

  // Shared content for all states - used by both FULL and compact modes
  const content = (
    <div className="flex flex-col mb-1 space-y-2">
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

      {/* Code block */}
      {code && (
        <div className="prose max-w-full">
          <CodeBlock className="language-python" codeText={code.trim()}>
            <HighlightedPythonCode code={code.trim()} />
          </CodeBlock>
        </div>
      )}

      {/* Output */}
      {stdout && (
        <div className="rounded-md bg-background-neutral-02 p-3">
          <div className="text-xs font-semibold mb-1 text-text-03">
            {t("python.output.label")}
          </div>
          <pre className="text-sm whitespace-pre-wrap font-mono text-text-01 overflow-x-auto">
            {stdout}
          </pre>
        </div>
      )}

      {/* Error */}
      {stderr && (
        <div className="rounded-md bg-status-error-01 p-3 border border-status-error-02">
          <div className="text-xs font-semibold mb-1 text-status-error-05">
            {t("python.error.label")}
          </div>
          <pre className="text-sm whitespace-pre-wrap font-mono text-status-error-05 overflow-x-auto">
            {stderr}
          </pre>
        </div>
      )}

      {/* File count */}
      {generatedFileCount > 0 && (
        <div className="text-sm text-text-03">
          {t("python.generatedFiles.label", { count: generatedFileCount })}
        </div>
      )}

      {/* No output fallback - only when complete with no output */}
      {isComplete && !stdout && !stderr && (
        <div className="py-2 text-center text-text-04">
          <SvgTerminal className="w-4 h-4 mx-auto mb-1 opacity-50" />
          <p className="text-xs">{t("python.noOutput.text")}</p>
        </div>
      )}
    </div>
  );

  // FULL mode: render content directly
  if (renderType === RenderType.FULL) {
    return children([
      {
        icon: SvgTerminal,
        status,
        content,
        supportsCollapsible: true,
        alwaysCollapsible: true,
      },
    ]);
  }

  // Compact mode: wrap content in FadeDiv
  return children([
    {
      icon: SvgTerminal,
      status,
      supportsCollapsible: true,
      alwaysCollapsible: true,
      content: (
        <FadingEdgeContainer
          direction="bottom"
          className="max-h-24 overflow-hidden"
        >
          {content}
        </FadingEdgeContainer>
      ),
    },
  ]);
};
