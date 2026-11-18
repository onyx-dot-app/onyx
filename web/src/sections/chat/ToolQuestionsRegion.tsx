"use client";

import { useMemo } from "react";
import { Section } from "@opal/layouts";
import ToolQuestionCard from "@/app/app/message/messageComponents/ToolQuestionCard";
import { useCurrentMessageTree } from "@/app/app/stores/useChatSessionStore";
import {
  readWaitingQuestions,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";

interface ToolQuestionsRegionProps {
  className?: string;
}

/**
 * Every question card on the selected branch that waits for the user's
 * answers, oldest first. It follows the last message. An answered card shows
 * its record here until the resolution arrives; from then on the reply's
 * timeline shows the record.
 */
export default function ToolQuestionsRegion({
  className,
}: ToolQuestionsRegionProps) {
  const tree = useCurrentMessageTree();
  const localAnswers = useToolRequestUi((state) => state.localAnswers);
  const waiting = useMemo(
    () => (tree ? readWaitingQuestions(tree, localAnswers) : []),
    [tree, localAnswers]
  );
  if (waiting.length === 0) return null;
  return (
    <div data-testid="tool-questions-region" className={className}>
      <Section gap={0.75} alignItems="stretch" height="auto">
        {waiting.map((question) => (
          <ToolQuestionCard
            key={question.request.question_request_id}
            question={question}
          />
        ))}
      </Section>
    </div>
  );
}
