import React, { useState, ReactNode, useCallback, useMemo, memo } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";

const CODE_BLOCK_PADDING = { padding: "1rem" };

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
          <FiCheck size={16} />
          <span>Copied!</span>
        </div>
      ) : (
        <div className="flex items-center space-x-2">
          <FiCopy size={16} />
          <span>Copy code</span>
        </div>
      )}
    </div>
  );

  if (typeof children === "string") {
    return (
      <span
        className={`
          font-mono 
          text-text-800 
          bg-background-50 
          border 
          border-background-300 
          rounded 
          align-bottom
          px-1
          py-[3px]
          text-xs 
          inline-block
          whitespace-pre-wrap 
          break-words 
          ${className}
        `}
      >
        {children}
      </span>
    );
  }

  const CodeContent = () => {
    if (!language) {
      return (
        <pre style={CODE_BLOCK_PADDING}>
          <code className={`text-sm ${className}`}>
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
      <pre className="overflow-x-scroll" style={CODE_BLOCK_PADDING}>
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
    <div className="overflow-x-hidden">
      {language && (
        <div className="flex mx-3 py-2 text-xs">
          {language}
          {codeText && <CopyButton />}
        </div>
      )}

      <CodeContent />
    </div>
  );
});

CodeBlock.displayName = "CodeBlock";
MemoizedCodeLine.displayName = "MemoizedCodeLine";
