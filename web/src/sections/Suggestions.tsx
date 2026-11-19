"use client";

import { useTranslations } from "next-intl";
import { OnSubmitProps } from "@/hooks/useChatController";
import { useActiveAgent } from "@/lib/agents/hooks";
import { AnalyticsEvent, track } from "@/lib/analytics/utils";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { useSuggestedQuestions } from "@/lib/suggestedQuestions/hooks";
import { markSuggestedQuestionUsed } from "@/lib/suggestedQuestions/svc";
import type { ShownQuestion } from "@/lib/suggestedQuestions/types";
import { Text } from "@opal/components";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";

export interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

/**
 * The buttons under the chat input. An agent's own starter messages always
 * win. On the Playground's default agent, the person gets questions written
 * from their own documents, or one line while those are being prepared.
 */
export default function Suggestions({ onSubmit }: SuggestionsProps) {
  const t = useTranslations("chat.suggestedQuestions");
  const activeAgent = useActiveAgent();
  const { suggestions, mutate } = useSuggestedQuestions(
    activeAgent?.id ?? null
  );

  function send(message: string) {
    onSubmit({
      message,
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  }

  function handleQuestionClick(question: ShownQuestion, position: number) {
    send(question.message);
    track(AnalyticsEvent.CLICKED_SUGGESTED_QUESTION, {
      position,
      private: question.private,
    });
    // The click must not wait for, or fail because of, the bookkeeping.
    void markSuggestedQuestionUsed(question.id).catch(() => undefined);
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

  if (activeAgent?.id !== DEFAULT_AGENT_ID || !suggestions) return null;

  if (suggestions.questions.length === 0) {
    if (suggestions.state === "ready") return null;
    return (
      <div className="max-w-(--app-page-main-content-width) w-full p-1">
        <Text as="p" font="main-ui-muted" color="text-03">
          {suggestions.state === "preparing"
            ? t("preparing.text")
            : t("noDocuments.text")}
        </Text>
      </div>
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
