"use client";

import { Button } from "@opal/components";
import { Text } from "@opal/components";
import SvgPlus from "@opal/icons/plus";
import SvgHistory from "@opal/icons/history";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";

interface TutorChatHeaderProps {
  agent: MinimalPersonaSnapshot | null;
  courseName: string | null;
  onNewConversation: () => void;
  onToggleHistory: () => void;
  historyOpen: boolean;
}

export default function TutorChatHeader({
  agent,
  courseName,
  onNewConversation,
  onToggleHistory,
  historyOpen,
}: TutorChatHeaderProps) {
  const displayName = agent?.name ?? "Tutor";

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-border-01 bg-background-neutral-01">
      <div className="flex items-center gap-3 min-w-0">
        <Button
          variant="default"
          prominence="tertiary"
          icon={SvgHistory}
          size="sm"
          onClick={onToggleHistory}
          tooltip={historyOpen ? "Hide history" : "Show history"}
        />
        <div className="flex flex-col min-w-0">
          <Text font="main-ui-action" color="text-01" nowrap>
            {displayName}
          </Text>
          {courseName && (
            <Text font="secondary-body" color="text-03" nowrap>
              {courseName}
            </Text>
          )}
        </div>
      </div>
      <Button
        variant="default"
        prominence="secondary"
        icon={SvgPlus}
        size="sm"
        onClick={onNewConversation}
      >
        New Chat
      </Button>
    </header>
  );
}
