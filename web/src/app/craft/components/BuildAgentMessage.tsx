"use client";

import { CopyButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import Logo from "@/refresh-components/Logo";
import { convertMarkdownTablesToTsv } from "@/app/app/message/copyingUtils";

interface BuildAgentMessageProps {
  /** Raw markdown text of the agent's response, used for the copy action. */
  copyText: string;
  /** Rendered message body (text chunks, tool cards, thinking, etc.). */
  children: React.ReactNode;
  /** Optional trailing content (e.g. approval cards) appended under the turn. */
  trailing?: React.ReactNode;
}

/**
 * BuildAgentMessage - Renders a single saved agent turn in the craft chat.
 *
 * Mirrors the main chat's agent message: the body is shown alongside the Onyx
 * logo, and a hover-revealed copy action (reusing the shared Opal `CopyButton`)
 * lets the user copy the agent's textual output.
 */
export default function BuildAgentMessage({
  copyText,
  children,
  trailing,
}: BuildAgentMessageProps) {
  const hasCopyableText = copyText.trim().length > 0;

  return (
    <Hoverable.Root group="craftAgentMessage" width="full">
      <div className="flex items-start gap-3 py-4">
        <div className="shrink-0 h-9 flex items-center">
          <Logo onyxBranded folded size={24} />
        </div>
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          {children}
          {hasCopyableText && (
            <Hoverable.Item group="craftAgentMessage" variant="appear-on-hover">
              <div className="flex pl-1">
                <CopyButton
                  getCopyText={() => convertMarkdownTablesToTsv(copyText)}
                  prominence="tertiary"
                  data-testid="CraftAgentMessage/copy-button"
                />
              </div>
            </Hoverable.Item>
          )}
          {trailing}
        </div>
      </div>
    </Hoverable.Root>
  );
}
