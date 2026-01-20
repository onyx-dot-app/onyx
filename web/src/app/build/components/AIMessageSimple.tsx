"use client";

import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { SvgLoader } from "@opal/icons";

interface AIMessageSimpleProps {
  content: string;
  isStreaming?: boolean;
}

/**
 * AIMessageSimple - Simple AI message display for text content
 *
 * Used when we have plain text content (not streaming packets).
 * For full streaming packet support, use AIBuildMessage.
 */
export default function AIMessageSimple({
  content,
  isStreaming = false,
}: AIMessageSimpleProps) {
  const hasContent = content.length > 0;

  return (
    <div className="flex items-start gap-3 py-4">
      <div className="shrink-0 mt-0.5">
        <Logo folded size={24} />
      </div>
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        {!hasContent && isStreaming ? (
          <div className="flex items-center gap-2 py-1">
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
            <Text secondaryBody text03>
              Thinking...
            </Text>
          </div>
        ) : (
          <>
            <div className="py-1">
              <MinimalMarkdown content={content} className="text-text-05" />
            </div>
            {isStreaming && (
              <div className="flex items-center gap-1">
                <SvgLoader className="size-3 stroke-text-03 animate-spin" />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
