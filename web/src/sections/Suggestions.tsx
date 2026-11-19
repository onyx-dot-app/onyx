"use client";

import { useTranslations } from "next-intl";
import { useActiveAgent } from "@/lib/agents/hooks";
import { AnalyticsEvent, track } from "@/lib/analytics/utils";
import type { ComposedMessage } from "@/lib/chat/types";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { useSuggestedQuestions } from "@/lib/suggestedQuestions/hooks";
import { markSuggestedQuestionUsed } from "@/lib/suggestedQuestions/svc";
import type { ShownQuestion } from "@/lib/suggestedQuestions/types";
import { Text } from "@opal/components";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";
import type { RichStr } from "@opal/types";

export interface SuggestionsProps {
  /** The input bar's send, so a click keeps the chosen models and options. */
  onChat: (composed: ComposedMessage) => void;
  /** Sending is blocked, as for the input bar: an answer is in progress or a
   * file is still uploading. A click then does nothing. */
  disabled?: boolean;
}

/**
 * The buttons under the chat input. An agent's own starter messages always
 * win. On the Playground's default agent, the person gets questions written
 * from their own documents, or one line while those are being prepared.
 */
export default function Suggestions({
  onChat,
  disabled = false,
}: SuggestionsProps) {
  const t = useTranslations("chat.suggestedQuestions");
  const activeAgent = useActiveAgent();
  const { suggestions, isLoading, mutate } = useSuggestedQuestions(
    activeAgent?.id ?? null
  );

  // A blocked send would still clear the draft and mark the question used.
  function send(message: string): boolean {
    if (disabled) return false;
    onChat({ message, mentions: [] });
    return true;
  }

  function handleQuestionClick(question: ShownQuestion, position: number) {
    if (!send(question.message)) return;
    track(AnalyticsEvent.CLICKED_SUGGESTED_QUESTION, {
      position,
      private: question.private,
    });
    // The click must not wait for, or fail because of, the bookkeeping. A
    // failure only means the question can come back on a later visit.
    void markSuggestedQuestionUsed(question.id).catch((error: unknown) =>
      console.error("Could not mark the suggested question used:", error)
    );
    void mutate(
      (current) =>
        current && {
          ...current,
          questions: current.questions.filter((q) => q.id !== question.id),
        },
      { revalidate: false }
    );
  }

  const starterMessages = activeAgent?.starter_messages ?? [];
  if (starterMessages.length > 0) {
    return (
      <SuggestionList
        items={starterMessages.map(({ message }, index) => ({
          key: String(index),
          message,
          onClick: () => send(message),
        }))}
      />
    );
  }

  if (activeAgent?.id !== DEFAULT_AGENT_ID) return null;
  if (!suggestions) {
    return isLoading ? <SuggestionsLine text={t("preparing.text")} /> : null;
  }

  if (suggestions.questions.length === 0) {
    if (suggestions.state === "ready") return null;
    return (
      <SuggestionsLine
        text={
          suggestions.state === "preparing"
            ? t("preparing.text")
            : t("noDocuments.text")
        }
      />
    );
  }

  return (
    <SuggestionList
      items={suggestions.questions.map((question, position) => ({
        key: question.id,
        message: question.message,
        onClick: () => handleQuestionClick(question, position),
      }))}
    />
  );
}

interface SuggestionsLineProps {
  text: string | RichStr;
}

/** One line in place of the buttons, while there are none to show. */
function SuggestionsLine({ text }: SuggestionsLineProps) {
  return (
    <div className="max-w-(--app-page-main-content-width) w-full p-1">
      <Text as="p" font="main-ui-muted" color="text-03">
        {text}
      </Text>
    </div>
  );
}

interface SuggestionItem {
  key: string;
  message: string;
  onClick: () => void;
}

interface SuggestionListProps {
  items: SuggestionItem[];
}

function SuggestionList({ items }: SuggestionListProps) {
  return (
    <div className="max-w-(--app-page-main-content-width) flex flex-col w-full p-1">
      {items.map(({ key, message, onClick }) => (
        <Interactive.Stateless
          key={key}
          variant="default"
          prominence="tertiary"
          onClick={onClick}
        >
          <Interactive.Container width="full" rounding={2} size="lg">
            <Content
              font="main-ui-body"
              title={message}
              width="full"
              titleColor="text-03"
            />
          </Interactive.Container>
        </Interactive.Stateless>
      ))}
    </div>
  );
}
