"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, InputTypeIn, SelectCard, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import { SvgCheckSquare, SvgClock, SvgLoader, SvgX } from "@opal/icons";
import CometEdge from "@/refresh-components/CometEdge";
import type {
  ToolQuestion,
  ToolQuestionAnswer,
} from "@/app/app/services/streamingModels";
import type { ChatStream } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { postQuestionAnswers } from "@/lib/chat/svc";
import { fetchErrorDetail } from "@/lib/fetcher";
import {
  isClosedRequestError,
  useFollowUserInput,
  useNudgedCard,
} from "@/lib/chat/hooks";
import {
  type ToolQuestionCall,
  type ToolQuestionStatus,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";

interface ToolQuestionCardProps {
  question: ToolQuestionCall;
}

interface Choice {
  optionLabel: string | null;
  note: string;
}

const NO_CHOICE: Choice = { optionLabel: null, note: "" };

/** The card's answer to one question: an option, a note, or both. */
function answerOf(question: ToolQuestion, choice: Choice): ToolQuestionAnswer {
  const note = choice.note.trim();
  return {
    question_id: question.id,
    option_label: choice.optionLabel,
    user_note: note || null,
  };
}

/**
 * The agent's questions to the user. While they wait, the card shows one
 * question per page; each offers its options, in the model's order, and an
 * "Other" answer, one of which answers it. Back and Next move between the pages and keep the choices;
 * the last page submits once every question has an answer. Once they end, a
 * record shows the answers.
 * A message that the user types in the chat also answers them; it shows as
 * the user's message after the record.
 */
function ToolQuestionCard({ question }: ToolQuestionCardProps) {
  const { request, status } = question;
  const t = useTranslations("chat.messages.toolQuestion");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const card = useNudgedCard(request.question_request_id);
  const follow = useFollowUserInput();
  const [choices, setChoices] = useState<ReadonlyMap<string, Choice>>(
    () => new Map()
  );
  const [page, setPage] = useState(0);
  // Takes the focus after Back or Next, so screen readers read the new page.
  const pageRef = useRef<HTMLDivElement>(null);
  const pageTurned = useRef(false);
  const hintId = useId();
  const [submitting, setSubmitting] = useState(false);
  // The server's reason, such as a rejection by the admin's query hook.
  const [error, setError] = useState<string | null>(null);

  const choiceOf = (item: ToolQuestion) => choices.get(item.id) ?? NO_CHOICE;
  const setChoice = (item: ToolQuestion, choice: Choice) =>
    setChoices((current) => new Map(current).set(item.id, choice));
  const total = request.questions.length;
  const isLastPage = page === total - 1;
  const unanswered = request.questions.flatMap((item, index) => {
    const { optionLabel, note } = choiceOf(item);
    return optionLabel !== null || note.trim() !== "" ? [] : [index + 1];
  });
  const complete = unanswered.length === 0;

  // The answered status shows until the resolution packet confirms it.
  async function submit() {
    const { recordAnswer } = useToolRequestUi.getState();
    const sessionId = useChatSessionStore.getState().currentSessionId;
    const answers = request.questions.map((item) =>
      answerOf(item, choiceOf(item))
    );
    setSubmitting(true);
    setError(null);
    let continuation: ChatStream | null;
    try {
      const response = await postQuestionAnswers(request.question_request_id, {
        answers,
      });
      continuation = response.continuation;
      recordAnswer(request.question_request_id, {
        kind: "answered",
        answers,
        message: null,
      });
    } catch (cause) {
      if (isClosedRequestError(cause)) {
        recordAnswer(request.question_request_id, { kind: "closed" });
        if (sessionId !== null) await follow.refused(sessionId);
      } else {
        console.error("Failed to submit answers:", cause);
        setError(fetchErrorDetail(cause) ?? t("submitError"));
      }
      return;
    } finally {
      setSubmitting(false);
    }
    if (sessionId !== null) await follow.continued(sessionId, continuation);
  }

  const headline = t("header", { count: total });
  const item = request.questions[page];
  const choice = item ? choiceOf(item) : NO_CHOICE;
  const footerHint =
    total > 1 && isLastPage && !complete
      ? t("page.unanswered", {
          count: unanswered.length,
          numbers: format.list(unanswered.map(String)),
        })
      : null;

  function turnTo(next: number) {
    pageTurned.current = true;
    setPage(next);
  }

  useEffect(() => {
    if (!pageTurned.current) return;
    pageTurned.current = false;
    pageRef.current?.focus();
  }, [page]);

  return (
    <div
      ref={card.ref}
      data-testid="tool-question-card"
      className={cn(card.shaking && "motion-safe:animate-shake")}
      onAnimationEnd={card.onAnimationEnd}
    >
      {status.kind !== "pending" ? (
        <QuestionRecord questions={request.questions} status={status} />
      ) : (
        <CometEdge active tone="info" speedSeconds={3.6}>
          <div className="rounded-08 border border-status-info-03 overflow-hidden bg-background-neutral-00 p-4">
            <Section gap={4} alignItems="stretch" height="auto">
              <Section
                flexDirection="row"
                justifyContent="between"
                gap={4}
                height="auto"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={2}
                  width="fit"
                  height="auto"
                >
                  <SvgLoader className="size-4 shrink-0 stroke-status-info-05 motion-safe:animate-spin" />
                  <Text
                    as="p"
                    font="main-ui-muted"
                    color="text-04"
                    role="status"
                  >
                    {headline}
                  </Text>
                </Section>
                {total > 1 && (
                  <Text
                    as="p"
                    font="secondary-body"
                    color="text-03"
                    aria-live="polite"
                  >
                    {t("page.progress", { current: page + 1, total })}
                  </Text>
                )}
              </Section>
              {item && (
                <div
                  ref={pageRef}
                  role="group"
                  aria-label={item.header}
                  tabIndex={-1}
                  className="outline-none"
                >
                  <Section gap={3} alignItems="stretch" height="auto">
                    <Content
                      font="main-ui-action"
                      title={item.question}
                      description={item.header}
                    />
                    <QuestionOptions
                      key={item.id}
                      question={item}
                      selected={choice.optionLabel}
                      onSelect={(optionLabel) =>
                        setChoice(item, { optionLabel, note: "" })
                      }
                    />
                    <InputTypeIn
                      key={`${item.id}-note`}
                      value={choice.note}
                      placeholder={t("other.placeholder")}
                      aria-label={t("other.ariaLabel", {
                        header: item.header,
                      })}
                      onChange={(event) =>
                        setChoice(item, {
                          optionLabel: null,
                          note: event.target.value,
                        })
                      }
                    />
                  </Section>
                </div>
              )}
              {error && (
                <Text
                  as="p"
                  role="alert"
                  font="secondary-body"
                  color="status-error-05"
                >
                  {error}
                </Text>
              )}
              <Section
                flexDirection="row"
                justifyContent="between"
                gap={4}
                wrap
                height="auto"
              >
                <Text id={hintId} font="secondary-body" color="text-03">
                  {footerHint ?? ""}
                </Text>
                <Section
                  flexDirection="row"
                  justifyContent="end"
                  gap={2}
                  width="fit"
                  height="auto"
                >
                  {total > 1 && (
                    <Button
                      prominence="secondary"
                      size="sm"
                      disabled={page === 0}
                      onClick={() => turnTo(page - 1)}
                    >
                      {tCommon("backButton.label")}
                    </Button>
                  )}
                  {/* Next turns into Submit on the last page. */}
                  <Button
                    prominence="primary"
                    size="sm"
                    disabled={isLastPage && (!complete || submitting)}
                    aria-describedby={footerHint ? hintId : undefined}
                    onClick={() =>
                      isLastPage ? void submit() : turnTo(page + 1)
                    }
                  >
                    {isLastPage ? t("submit") : t("page.next")}
                  </Button>
                </Section>
              </Section>
            </Section>
          </div>
        </CometEdge>
      )}
    </div>
  );
}

const OPTION_KEYS = new Set([
  "ArrowDown",
  "ArrowUp",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
]);

interface QuestionOptionsProps {
  question: ToolQuestion;
  selected: string | null;
  onSelect: (optionLabel: string) => void;
}

/**
 * One question's options as a radio group: one tab stop, on the chosen
 * option or else the first; arrow keys, Home and End move the choice, and
 * Space or Enter chooses the focused option.
 */
function QuestionOptions({
  question,
  selected,
  onSelect,
}: QuestionOptionsProps) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const { options } = question;
  const current = options.findIndex((option) => option.label === selected);
  function move(index: number, key: string) {
    const last = options.length - 1;
    const next =
      key === "Home"
        ? 0
        : key === "End"
          ? last
          : key === "ArrowDown" || key === "ArrowRight"
            ? index === last
              ? 0
              : index + 1
            : index === 0
              ? last
              : index - 1;
    const option = options[next];
    if (!option) return;
    onSelect(option.label);
    refs.current[next]?.focus();
  }
  return (
    <div role="radiogroup" aria-label={question.question}>
      <Section gap={2} alignItems="stretch" height="auto">
        {options.map((option, index) => {
          const isSelected = index === current;
          return (
            <SelectCard
              key={option.label}
              ref={(element: HTMLElement | null) => {
                refs.current[index] =
                  element instanceof HTMLDivElement ? element : null;
              }}
              role="radio"
              aria-checked={isSelected}
              tabIndex={index === Math.max(current, 0) ? 0 : -1}
              state={isSelected ? "selected" : "empty"}
              padding={2}
              rounding={2}
              onClick={() => onSelect(option.label)}
              onKeyDown={(event) => {
                if (!OPTION_KEYS.has(event.key)) return;
                event.preventDefault();
                move(index, event.key);
              }}
            >
              <Content
                font="main-ui-body"
                title={option.label}
                description={option.description || undefined}
              />
            </SelectCard>
          );
        })}
      </Section>
    </div>
  );
}

interface QuestionRecordProps {
  questions: ToolQuestion[];
  status: Exclude<ToolQuestionStatus, { kind: "pending" }>;
}

/**
 * How the questions ended, in one line, and below it each answer from the
 * card, or else each question.
 */
function QuestionRecord({ questions, status }: QuestionRecordProps) {
  const t = useTranslations("chat.messages.toolQuestion");
  const answers =
    status.kind === "answered" && status.answers ? status.answers : null;
  const title =
    status.kind === "answered"
      ? t(answers ? "record.answered" : "record.answeredInChat")
      : t(`record.${status.kind}`);
  const lines = questions.map((item) => {
    const answer = answers?.find((entry) => entry.question_id === item.id);
    if (!answers) return { id: item.id, text: item.question };
    const option = answer?.option_label ?? null;
    const note = answer?.user_note ?? null;
    return {
      id: item.id,
      text: t("record.answer", {
        header: item.header,
        answer:
          option && note
            ? t("record.optionAndNote", { option, note })
            : (option ?? note ?? ""),
      }),
    };
  });
  return (
    <Section gap={1} alignItems="stretch" height="auto">
      <div role="status">
        <Content
          font="main-ui-muted"
          icon={
            status.kind === "answered"
              ? SvgCheckSquare
              : status.kind === "cancelled"
                ? SvgX
                : SvgClock
          }
          title={title}
        />
      </div>
      <div className="ps-6">
        <Section gap={1} alignItems="stretch" height="auto">
          {lines.map((line) => (
            <Text
              key={line.id}
              as="p"
              font="secondary-body"
              color="text-03"
              wordWrap="wrap-anywhere"
            >
              {line.text}
            </Text>
          ))}
        </Section>
      </div>
    </Section>
  );
}

// Callers rebuild question calls on every streamed packet; the request object
// and status stay the same until something changes.
export default memo(
  ToolQuestionCard,
  (prev, next) =>
    prev.question.request === next.question.request &&
    prev.question.status === next.question.status
);
