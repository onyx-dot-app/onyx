"use client";

import { useCallback, useMemo } from "react";
import { ChatSession } from "@/app/app/interfaces";
import { Text } from "@opal/components";
import { Button } from "@opal/components";
import { Interactive } from "@opal/core";
import SvgX from "@opal/icons/x";
import { UNNAMED_CHAT } from "@/lib/constants";
import { cn } from "@/lib/utils";

interface TutorHistoryPanelProps {
  sessions: ChatSession[];
  currentSessionId: string | null;
  // Persona IDs that belong to the current course. When provided, only
  // sessions whose persona is in this set are shown. Pass null to skip
  // filtering (e.g., while the course-tutor list is still loading).
  allowedPersonaIds: Set<number> | null;
  onSelectSession: (sessionId: string) => void;
  onClose: () => void;
}

/** Group sessions by relative date label. */
function groupByDate(
  sessions: ChatSession[]
): { label: string; sessions: ChatSession[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, ChatSession[]> = {};
  const order: string[] = [];

  for (const session of sessions) {
    const d = new Date(session.time_updated);
    let label: string;
    if (d >= today) {
      label = "Today";
    } else if (d >= yesterday) {
      label = "Yesterday";
    } else if (d >= weekAgo) {
      label = "This Week";
    } else {
      label = d.toLocaleDateString(undefined, {
        month: "short",
        year: "numeric",
      });
    }
    if (!groups[label]) {
      groups[label] = [];
      order.push(label);
    }
    groups[label]!.push(session);
  }

  return order.map((label) => ({ label, sessions: groups[label]! }));
}

export default function TutorHistoryPanel({
  sessions,
  currentSessionId,
  allowedPersonaIds,
  onSelectSession,
  onClose,
}: TutorHistoryPanelProps) {
  // Filter sessions to only those whose persona belongs to the current course.
  const filteredSessions = useMemo(() => {
    if (allowedPersonaIds === null) return sessions;
    return sessions.filter((s) => allowedPersonaIds.has(s.persona_id));
  }, [sessions, allowedPersonaIds]);

  const grouped = useMemo(
    () => groupByDate(filteredSessions),
    [filteredSessions]
  );

  const handleSelect = useCallback(
    (id: string) => {
      onSelectSession(id);
    },
    [onSelectSession]
  );

  return (
    <div className="flex flex-col h-full w-[280px] border-r border-border-01 bg-background-neutral-01">
      {/* Panel header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-01">
        <Text font="main-ui-action" color="text-01">
          History
        </Text>
        <Button
          variant="default"
          prominence="tertiary"
          icon={SvgX}
          size="xs"
          onClick={onClose}
        />
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {grouped.length === 0 && (
          <div className="p-4">
            <Text font="secondary-body" color="text-03">
              No conversations yet.
            </Text>
          </div>
        )}
        {grouped.map((group) => (
          <div key={group.label}>
            <div className="px-3 pt-3 pb-1">
              <Text font="secondary-action" color="text-03">
                {group.label}
              </Text>
            </div>
            {group.sessions.map((session) => (
              <Interactive.Stateful
                key={session.id}
                variant="select-light"
                state={session.id === currentSessionId ? "selected" : "empty"}
                onClick={() => handleSelect(session.id)}
              >
                <Interactive.Container
                  widthVariant="full"
                  roundingVariant="sm"
                  heightVariant="md"
                >
                  <div
                    className={cn(
                      "px-3 py-1.5 w-full truncate",
                      session.id === currentSessionId && "font-medium"
                    )}
                  >
                    <Text
                      font="main-ui-body"
                      color={
                        session.id === currentSessionId ? "text-01" : "text-02"
                      }
                      nowrap
                    >
                      {session.name || UNNAMED_CHAT}
                    </Text>
                  </div>
                </Interactive.Container>
              </Interactive.Stateful>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
