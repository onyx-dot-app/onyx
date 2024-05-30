import React from "react";
import { useState, ReactNode } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";

interface CodeBlockProps {
  className?: string | undefined;
  children?: ReactNode;
  content: string;
  [key: string]: any;
}

export function CodeBlock({
  className = "",
  children,
  content,
  ...props
}: CodeBlockProps) {
  const language = className
    .split(" ")
    .filter((cls) => cls.startsWith("language-"))
    .map((cls) => cls.replace("language-", ""))
    .join(" ");
  const [copied, setCopied] = useState(false);

  if (!language) {
    return (
      <code {...props} className={`text-sm ${className}`}>
        {children}
      </code>
    );
  }

  let codeText: string | null = null;
  if (
    props.node?.position?.start?.offset &&
    props.node?.position?.end?.offset
  ) {
    codeText = content.slice(
      props.node.position.start.offset,
      props.node.position.end.offset
    );

    // Remove the language declaration and trailing backticks
    const codeLines = codeText.split("\n");
    if (codeLines.length > 1 && codeLines[0].startsWith("```")) {
      codeLines.shift(); // Remove the first line with the language declaration
      if (codeLines[codeLines.length - 1] === "```") {
        codeLines.pop(); // Remove the last line with the trailing backticks
      }
      codeText = codeLines.join("\n");
    }
  }

  // handle unknown languages. They won't have a `node.position.start.offset`
  if (!codeText) {
    const findTextNode = (node: any): string | null => {
      if (node.type === "text") {
        return node.value;
      }
      let finalResult = "";
      if (node.children) {
        for (const child of node.children) {
          const result = findTextNode(child);
          if (result) {
            finalResult += result;
          }
        }
      }
      return finalResult;
    };

    codeText = findTextNode(props.node);
  }

  const handleCopy = () => {
    if (!codeText) {
      return;
    }

    navigator.clipboard.writeText(codeText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000); // Reset copy status after 2 seconds
    });
  };

  return (
    <div className="overflow-x-hidden">
      <div className="flex mx-3 py-2 text-xs">
        {language}
        {codeText && (
          <div
            className="ml-auto cursor-pointer select-none"
            onClick={handleCopy}
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
        )}
      </div>
      <pre {...props} className="overflow-x-scroll" style={{ padding: "1rem" }}>
        <code className={`text-sm overflow-x-auto ${className}`}>
          {children}
        </code>
      </pre>
    </div>
  );
}
