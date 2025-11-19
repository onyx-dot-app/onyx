import SvgCheck from "@/icons/check";
import SvgCode from "@/icons/code";
import SvgCopy from "@/icons/copy";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import React, { useState, ReactNode, useCallback, useMemo, memo } from "react";

interface CodeBlockProps {
  className?: string;
  children?: ReactNode;
  codeText: string;
}

const MemoizedCodeLine = memo(({ content }: { content: ReactNode }) => (
  <>{content}</>
));

export const CodeBlock = memo(function CodeBlock({
  className = "",
  children,
  codeText,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const language = useMemo(() => {
    return className
      .split(" ")
      .filter((cls) => cls.startsWith("language-"))
      .map((cls) => cls.replace("language-", ""))
      .join(" ");
  }, [className]);

  const handleCopy = useCallback(() => {
    if (!codeText) return;
    navigator.clipboard.writeText(codeText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [codeText]);

  const CopyButton = () => (
    <div
      className="ml-auto cursor-pointer select-none"
      onMouseDown={handleCopy}
    >
      {copied ? (
        <div className="flex items-center space-x-2">
          <SvgCheck height={14} width={14} stroke="currentColor" />
          <Text secondaryMono>Copied!</Text>
        </div>
      ) : (
        <div className="flex items-center space-x-2">
          <SvgCopy height={14} width={14} stroke="currentColor" />
          <Text secondaryMono>Copy code</Text>
        </div>
      )}
    </div>
  );

  if (typeof children === "string" && !language) {
    return (
      <span
        className={cn(
          "font-mono",
          "text-text-05",
          "bg-background-tint-00",
          "rounded",
          "align-bottom",
          "text-xs",
          "inline-block",
          "whitespace-pre-wrap",
          "break-words",
          "py-0.5",
          "px-1",
          className
        )}
      >
        {children}
      </span>
    );
  }

  const CodeContent = () => {
    if (!language) {
      return (
        <pre className="!p-2 hljs">
          <code className={`text-sm hljs ${className}`}>
            {Array.isArray(children)
              ? children.map((child, index) => (
                  <MemoizedCodeLine key={index} content={child} />
                ))
              : children}
          </code>
        </pre>
      );
    }

    return (
      <pre className="!p-2 hljs">
        <code className="text-xs overflow-x-auto">
          {Array.isArray(children)
            ? children.map((child, index) => (
                <MemoizedCodeLine key={index} content={child} />
              ))
            : children}
        </code>
      </pre>
    );
  };

  return (
    <div className="overflow-x-hidden bg-background-tint-00 px-1 pb-1 rounded-12">
      {language && (
        <div className="flex px-2 py-1 text-sm text-text-04 gap-x-2">
          <SvgCode
            height={12}
            width={12}
            stroke="currentColor"
            className="my-auto"
          />
          <Text secondaryMono>{language}</Text>
          {codeText && <CopyButton />}
        </div>
      )}

      <CodeContent />
    </div>
  );
});

CodeBlock.displayName = "CodeBlock";
MemoizedCodeLine.displayName = "MemoizedCodeLine";
