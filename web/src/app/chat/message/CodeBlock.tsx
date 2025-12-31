import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import React, { useState, ReactNode, useCallback, useMemo, memo } from "react";
import { SvgCheck, SvgCode, SvgCopy } from "@opal/icons";

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
          <Text as="p" secondaryMono>
            Copied!
          </Text>
        </div>
      ) : (
        <div className="flex items-center space-x-2">
          <SvgCopy height={14} width={14} stroke="currentColor" />
          <Text as="p" secondaryMono>
            Copy
          </Text>
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
        <pre className="!p-2 m-0 overflow-x-auto w-0 min-w-full hljs">
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
      <pre className="!p-2 m-0 overflow-x-auto w-0 min-w-full hljs">
        <code className="text-xs">
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
    <div className="bg-background-tint-00 px-1 pb-1 rounded-12 max-w-full min-w-0">
      {language && (
        <div className="flex items-center px-2 py-1 text-sm text-text-04 gap-x-2">
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
