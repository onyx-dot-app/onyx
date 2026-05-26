"use client";

import { useCallback, useMemo } from "react";
import { ChatSession } from "@/app/app/interfaces";
import { Button, Text } from "@opal/components";
import { Interactive } from "@opal/core";
import SvgHistory from "@opal/icons/history";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Modal from "@/refresh-components/Modal";
import { UNNAMED_CHAT } from "@/lib/constants";
import { cn } from "@/lib/utils";

interface TutorHistoryPanelProps {
  open: boolean;
  sessions: ChatSession[];
  currentSessionId: string | null;
  allowedPersonaIds: Set<number> | null;
  personaNameById: Map<number, string> | null;
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
  onSelectSession: (session: ChatSession) => void;
  onClose: () => void;
}

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
  open,
  sessions,
  currentSessionId,
  allowedPersonaIds,
  personaNameById,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
  onSelectSession,
  onClose,
}: TutorHistoryPanelProps) {
  const filteredSessions = useMemo(() => {
    if (allowedPersonaIds === null) return sessions;
    return sessions.filter((s) => allowedPersonaIds.has(s.persona_id));
  }, [sessions, allowedPersonaIds]);

  const grouped = useMemo(
    () => groupByDate(filteredSessions),
    [filteredSessions]
  );

  const handleSelect = useCallback(
    (session: ChatSession) => {
      onSelectSession(session);
    },
    [onSelectSession]
  );

  return (
    <Modal
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <Modal.Content width="md" height="lg" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgHistory}
          title="History"
          description="Tutor conversations for this class"
          onClose={onClose}
        />
        <Modal.Body twoTone={false} padding={0}>
          <div className="flex min-h-0 w-full flex-col">
            {isLoading ? (
              <div className="flex h-40 items-center justify-center">
                <SimpleLoader className="h-6 w-6" />
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto py-2">
                {grouped.length === 0 && (
                  <div className="px-4 py-8 text-center">
                    <Text font="secondary-body" color="text-03">
                      No conversations yet.
                    </Text>
                  </div>
                )}
                {grouped.map((group) => (
                  <div key={group.label}>
                    <div className="px-4 pb-1 pt-3">
                      <Text font="secondary-action" color="text-03">
                        {group.label}
                      </Text>
                    </div>
                    <div className="px-2">
                      {group.sessions.map((session) => {
                        const tutorName = personaNameById?.get(
                          session.persona_id
                        );

                        return (
                          <Interactive.Stateful
                            key={session.id}
                            variant="select-light"
                            state={
                              session.id === currentSessionId
                                ? "selected"
                                : "empty"
                            }
                            onClick={() => handleSelect(session)}
                          >
                            <Interactive.Container
                              widthVariant="full"
                              roundingVariant="sm"
                              heightVariant="md"
                            >
                              <div
                                className={cn(
                                  "flex w-full min-w-0 flex-col px-3 py-1.5",
                                  session.id === currentSessionId &&
                                    "font-medium"
                                )}
                              >
                                <Text
                                  font="main-ui-body"
                                  color={
                                    session.id === currentSessionId
                                      ? "text-01"
                                      : "text-02"
                                  }
                                  nowrap
                                >
                                  {session.name || UNNAMED_CHAT}
                                </Text>
                                {tutorName && (
                                  <Text
                                    font="secondary-body"
                                    color="text-03"
                                    nowrap
                                  >
                                    {tutorName}
                                  </Text>
                                )}
                              </div>
                            </Interactive.Container>
                          </Interactive.Stateful>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {hasMore && (
              <div className="border-t border-border-01 p-3">
                <Button
                  variant="default"
                  prominence="secondary"
                  disabled={isLoadingMore}
                  onClick={onLoadMore}
                >
                  {isLoadingMore ? "Loading..." : "Load more"}
                </Button>
              </div>
            )}
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
