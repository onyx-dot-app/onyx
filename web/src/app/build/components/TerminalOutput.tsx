"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgTerminalSmall, SvgLoader } from "@opal/icons";

interface TerminalOutputProps {
  output: string;
  isStreaming: boolean;
}

export default function TerminalOutput({
  output,
  isStreaming,
}: TerminalOutputProps) {
  const containerRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (isStreaming && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [output, isStreaming]);

  return (
    <div className="border border-border-02 rounded-12 overflow-hidden">
      <div className="p-2 bg-background-neutral-01 flex flex-row items-center justify-between gap-2">
        <div className="flex flex-row items-center gap-1.5">
          <SvgTerminalSmall className="size-4 stroke-text-03" />
          <Text mainUiAction text03>
            Output
          </Text>
        </div>
        {isStreaming && (
          <div className="flex flex-row items-center gap-1.5">
            <SvgLoader className="size-4 stroke-status-success-05 animate-spin" />
            <Text secondaryBody className="text-status-success-05">
              Streaming
            </Text>
          </div>
        )}
      </div>
      <pre
        ref={containerRef}
        className={cn(
          "p-4 bg-background-inverted-neutral-03 font-main-content-mono text-text-inverted-03",
          "overflow-auto max-h-96 text-sm"
        )}
      >
        {output || "Waiting for output..."}
      </pre>
    </div>
  );
}
