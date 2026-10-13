"use client";

import { useMemo, type ComponentPropsWithoutRef } from "react";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { MemoizedLink } from "@/app/app/message/MemoizedTextComponents";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { buildArtifactUrl } from "@/app/craft/services/apiServices";
import { parseOutputLink } from "@/app/craft/utils/pathSanitizer";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";
import { useTypewriter } from "@/hooks/useTypewriter";

interface TextChunkProps {
  sessionId: string | null;
  content: string;
  /** True while this text is actively streaming in. */
  isStreaming?: boolean;
}

export default function TextChunk({
  sessionId,
  content,
  isStreaming = false,
}: TextChunkProps) {
  const { enabled: smoothStreaming } = useSmoothStreaming();
  const animate = isStreaming && smoothStreaming;
  const { displayed } = useTypewriter(content, animate, !isStreaming);
  const visible = animate ? displayed : content;
  const openFilePreview = useBuildSessionStore(
    (state) => state.openFilePreview
  );
  const components = useMemo(
    () => ({
      a: function MessageLink({
        href,
        children,
      }: ComponentPropsWithoutRef<"a">) {
        if (!href || !/^(?:\.\/)?outputs(?:[/\\%]|$)/.test(href)) {
          return <MemoizedLink href={href}>{children}</MemoizedLink>;
        }
        const path = parseOutputLink(href);
        if (!path || !sessionId) return <>{children}</>;

        return (
          <a
            href={buildArtifactUrl(sessionId, path)}
            className="cursor-pointer text-link hover:text-link-hover"
            onClick={(event) => {
              event.preventDefault();
              openFilePreview(sessionId, path, path.split("/").pop() ?? path);
            }}
          >
            {children}
          </a>
        );
      },
    }),
    [sessionId, openFilePreview]
  );

  if (!visible && !isStreaming) return null;

  return (
    <div className="py-1">
      <MinimalMarkdown
        content={visible}
        className="text-text-05"
        streaming={isStreaming}
        components={components}
      />
      {isStreaming && <BlinkingBar />}
    </div>
  );
}
