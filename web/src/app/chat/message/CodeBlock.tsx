import React, { useState, ReactNode, useCallback, useMemo, memo, useEffect } from "react"; // Added useEffect
import { FiCheck, FiCopy } from "react-icons/fi";
import KrokiDiagram from "@/components/chat/KrokiDiagram";

const CODE_BLOCK_PADDING = { padding: "1rem" };

// Added: List of supported diagram types by Kroki
// This should ideally be kept in sync with the backend or a shared constants file
const SUPPORTED_KROKI_LANGUAGES = new Set([
  "blockdiag", "seqdiag", "actdiag", "nwdiag", "packetdiag", "rackdiag",
  "graphviz", "pikchr", "erd", "excalidraw", "vega", "vegalite",
  "ditaa", "mermaid", "nomnoml", "plantuml", "bpmn", "bytefield",
  "wavedrom", "svgbob", "c4plantuml", "structurizr", "umlet",
  "wireviz", "symbolator"
]);

// Module-level flag to track if Kroki feature is confirmed disabled for the session
let isKrokiFeatureConfirmedDisabled = false;


interface CodeBlockProps {
  className?: string;
  children?: ReactNode;
  codeText: string;
  isFallback?: boolean; // Added prop to prevent recursion
}

const MemoizedCodeLine = memo(({ content }: { content: ReactNode }) => (
  <>{content}</>
));

export const CodeBlock = memo(function CodeBlock({
  className = "",
  children,
  codeText,
  isFallback = false, // Default to false
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  // Local state to force re-render if isKrokiFeatureConfirmedDisabled changes
  const [krokiDisabledSignal, setKrokiDisabledSignal] = useState(isKrokiFeatureConfirmedDisabled);

  useEffect(() => {
    // This effect ensures that if the global flag changes, this component instance re-evaluates
    if (isKrokiFeatureConfirmedDisabled !== krokiDisabledSignal) {
      setKrokiDisabledSignal(isKrokiFeatureConfirmedDisabled);
    }
  }, [krokiDisabledSignal]);


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

  // If Kroki is not confirmed disabled, language is supported,
  // it's a fenced code block, codeText is not empty, AND it's not already a fallback.
  if (
    !isFallback && // Check if this CodeBlock instance is NOT a fallback
    !isKrokiFeatureConfirmedDisabled &&
    language &&
    SUPPORTED_KROKI_LANGUAGES.has(language) &&
    typeof children !== "string" && 
    codeText.trim() !== ""
  ) {
    return (
      <KrokiDiagram
        diagramType={language}
        codeText={codeText}
        onFeatureDisabled={() => {
          if (!isKrokiFeatureConfirmedDisabled) {
            isKrokiFeatureConfirmedDisabled = true;
            setKrokiDisabledSignal(true); // Trigger re-render for other instances
          }
        }}
      />
    );
  }

  // Original CodeContent rendering logic for standard code blocks or when Kroki is not applicable
  const CodeContent = () => {
    if (!language) {
      // This typically handles cases where it might be a simple preformatted block
      // without a language, or if the language wasn't parsed correctly.
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

    // Standard fenced code block rendering
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

  // Original return structure for non-Kroki code blocks
  return (
    <div className="overflow-x-hidden">
      {language && typeof children !== "string" && ( // Only show header for fenced code blocks
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
