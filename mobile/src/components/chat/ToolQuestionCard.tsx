// The questions that the agent asks the user. A waiting request shows one question per page with
// its options and an "Other" choice that answers with typed text; a single-select question takes one
// of them, a multi-select question any of them. An answered one leaves a record of the answers, or
// of the message that the user typed in the chat instead.
import { memo, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Platform, Pressable, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";

import { postQuestionAnswers } from "@/api/chat/questions";
import { isApiError } from "@/api/errors";
import { ChatStream } from "@/chat/interfaces";
import {
  ToolQuestionAnswer,
  ToolQuestionItem,
  ToolQuestionOption,
} from "@/chat/streamingModels";
import {
  CLOSED_QUESTION,
  QuestionResolution,
  ToolQuestion,
  useToolQuestionUi,
} from "@/chat/toolQuestions";
import { UserMessageBubble } from "@/components/chat/UserMessageBubble";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import { TextInput } from "@/components/ui/text-input";
import { followUserAnswer } from "@/hooks/followUserAnswer";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import SvgBubbleText from "@/icons/bubble-text";
import SvgCheckCircle from "@/icons/check-circle";
import SvgCheckSquare from "@/icons/check-square";
import SvgCircle from "@/icons/circle";
import SvgClock from "@/icons/clock";
import SvgLoader from "@/icons/loader";
import SvgSquare from "@/icons/square";
import { cn } from "@/lib/utils";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";

// The choice that answers with a note instead of a listed option.
const OTHER = { label: "Other", description: "Type your own answer." };

const SUBMIT_FAILED = "Could not submit your answers. Try again.";

// The chosen options, and whether "Other" is chosen.
type Choice = { labels: readonly string[]; other: boolean };

const NO_CHOICE: Choice = { labels: [], other: false };

// iOS has no live regions; Android reads `accessibilityLiveRegion` instead.
function announce(message: string): void {
  if (Platform.OS === "ios")
    AccessibilityInfo.announceForAccessibility(message);
}

function answerText(answer: ToolQuestionAnswer): string {
  return [answer.option_labels.join(", "), answer.user_note]
    .filter((part): part is string => !!part)
    .join(" · ");
}

function recordText(resolution: QuestionResolution): string {
  if (resolution.outcome === "cancelled") return "No longer waiting";
  return resolution.answered_via === "message"
    ? "Answered in chat"
    : "Answered";
}

// A note answers only when it has text.
function questionAnswer(
  question: ToolQuestionItem,
  choice: Choice,
  note: string | undefined,
): ToolQuestionAnswer | null {
  // A saved question can repeat a label; each label counts once.
  const labels = [
    ...new Set(question.options.map((option) => option.label)),
  ].filter((label) => choice.labels.includes(label));
  const text = choice.other ? note?.trim() : undefined;
  if (labels.length === 0 && !text) return null;
  return text
    ? { question_id: question.id, option_labels: labels, user_note: text }
    : { question_id: question.id, option_labels: labels };
}

function unansweredHint(pages: number[]): string {
  const names = pages.map((page) => String(page + 1));
  const list =
    names.length === 1
      ? names[0]
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `Answer question${names.length === 1 ? "" : "s"} ${list} to submit.`;
}

function OptionRow({
  option,
  multiSelect,
  selected,
  disabled,
  onPress,
}: {
  option: ToolQuestionOption;
  multiSelect: boolean;
  selected: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole={multiSelect ? "checkbox" : "radio"}
      accessibilityLabel={`${option.label}. ${option.description}`}
      accessibilityState={{ checked: selected, disabled }}
      className={cn(
        "flex-row items-start gap-8 rounded-08 border px-8 py-8",
        selected
          ? "border-action-selection-03 bg-action-selection-02"
          : "border-border-01 active:bg-background-tint-02",
      )}
    >
      <Icon
        as={
          multiSelect
            ? selected
              ? SvgCheckSquare
              : SvgSquare
            : selected
              ? SvgCheckCircle
              : SvgCircle
        }
        size={16}
        className={selected ? "text-action-selection-05" : "text-text-03"}
      />
      <View className="flex-1 gap-2">
        <Text font="main-ui-action" color="text-05">
          {option.label}
        </Text>
        {option.description ? (
          <Text font="secondary-body" color="text-03">
            {option.description}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

function QuestionRecord({
  question,
  resolution,
  showsTypedAnswer,
}: {
  question: ToolQuestion;
  resolution: QuestionResolution;
  showsTypedAnswer: boolean;
}) {
  const record = recordText(resolution);
  const answers = new Map(
    (resolution.answers ?? []).map((answer) => [answer.question_id, answer]),
  );
  const lines = question.request.questions.flatMap((item) => {
    const answer = answers.get(item.id);
    return answer
      ? [{ id: item.id, text: `${item.header}: ${answerText(answer)}` }]
      : [];
  });
  return (
    <View className="gap-8">
      <View
        testID="tool-question-record"
        accessible
        accessibilityLiveRegion="polite"
        accessibilityLabel={[record, ...lines.map((line) => line.text)].join(
          ". ",
        )}
        className="flex-row items-start gap-6"
      >
        <Icon
          as={
            resolution.outcome === "cancelled"
              ? SvgClock
              : resolution.answered_via === "message"
                ? SvgBubbleText
                : SvgCheckSquare
          }
          size={16}
          className="text-text-04"
        />
        <View className="flex-1 gap-2">
          <Text font="main-ui-muted" color="text-04">
            {record}
          </Text>
          {lines.map((line) => (
            <Text key={line.id} font="secondary-body" color="text-04">
              {line.text}
            </Text>
          ))}
        </View>
      </View>
      {/* What the user typed in the chat shows as the user's message. */}
      {showsTypedAnswer && resolution.message ? (
        <View className="items-end">
          <UserMessageBubble text={resolution.message} />
        </View>
      ) : null}
    </View>
  );
}

function ToolQuestionCardComponent({
  question,
  showsTypedAnswer,
}: {
  question: ToolQuestion;
  // One typed message answers every waiting question of the response; one record shows it.
  showsTypedAnswer: boolean;
}) {
  const { request, resolution } = question;
  const reduceMotion = useReducedMotion();
  const serverUrl = useSession((state) => state.serverUrl);
  const queryClient = useQueryClient();
  // Maps, not objects: a question ID such as "constructor" must not read an inherited value.
  const [choices, setChoices] = useState<ReadonlyMap<string, Choice>>(
    () => new Map(),
  );
  const [notes, setNotes] = useState<ReadonlyMap<string, string>>(
    () => new Map(),
  );
  const [page, setPage] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const header =
    request.questions.length === 1 ? "Question for you" : "Questions for you";
  const message = resolution ? recordText(resolution) : header;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    // A loaded history of answered questions stays quiet; a new wait or a change speaks.
    if (announced.current === null && resolution !== null) {
      announced.current = message;
      return;
    }
    if (announced.current !== message) announce(message);
    announced.current = message;
  }, [message, resolution]);

  if (resolution !== null) {
    return (
      <QuestionRecord
        question={question}
        resolution={resolution}
        showsTypedAnswer={showsTypedAnswer}
      />
    );
  }

  const questionAnswers = request.questions.map((item) =>
    questionAnswer(item, choices.get(item.id) ?? NO_CHOICE, notes.get(item.id)),
  );
  const answers = questionAnswers.every(
    (answer): answer is ToolQuestionAnswer => answer !== null,
  )
    ? questionAnswers
    : null;
  const unanswered = questionAnswers.flatMap((answer, index) =>
    answer === null ? [index] : [],
  );
  const pageCount = request.questions.length;
  const lastPage = page === pageCount - 1;
  const item = request.questions[page]!;
  const choice = choices.get(item.id) ?? NO_CHOICE;
  const choose = (next: Choice) =>
    setChoices((current) => new Map(current).set(item.id, next));
  // A multi-select question toggles each choice; a single-select one keeps only the last.
  const chooseOption = (label: string) =>
    choose(
      item.multi_select
        ? {
            ...choice,
            labels: choice.labels.includes(label)
              ? choice.labels.filter((each) => each !== label)
              : [...choice.labels, label],
          }
        : { labels: [label], other: false },
    );
  const goToPage = (next: number) => {
    setPage(next);
    announce(`Question ${next + 1} of ${pageCount}`);
  };
  const submitHint =
    lastPage && pageCount > 1 && unanswered.length > 0
      ? unansweredHint(unanswered)
      : null;

  // The answers show at once; the resolution packet then confirms them.
  async function submit(given: ToolQuestionAnswer[]) {
    const { recordStatuses } = useToolQuestionUi.getState();
    // The card's chat; the user can open another one while the answer is in flight.
    const sessionId = useChatSessionStore.getState().currentSessionId;
    setSubmitting(true);
    setError(null);
    let continuation: ChatStream | null = null;
    try {
      const response = await postQuestionAnswers(request.question_request_id, {
        answers: given,
      });
      recordStatuses([request.question_request_id], {
        outcome: "answered",
        answered_via: "card",
        answers: given,
      });
      continuation = response.continuation;
    } catch (cause) {
      if (isApiError(cause) && (cause.status === 409 || cause.status === 404)) {
        recordStatuses([request.question_request_id], CLOSED_QUESTION);
      } else {
        // The server's reason for a refused answer, such as a blocked note; the answers stay.
        console.warn("Could not submit the answers", cause);
        const reason =
          isApiError(cause) && cause.status < 500 && cause.detail
            ? cause.detail
            : SUBMIT_FAILED;
        setError(reason);
        announce(reason);
        return;
      }
    } finally {
      setSubmitting(false);
    }
    followUserAnswer(sessionId, continuation, serverUrl, queryClient);
  }

  return (
    <View
      testID="tool-question-card"
      className="overflow-hidden rounded-08 border border-status-info-02 bg-background-neutral-00"
    >
      <View
        accessible
        accessibilityRole="header"
        accessibilityLiveRegion="polite"
        accessibilityLabel={header}
        className="flex-row items-center gap-8 px-12 py-8"
      >
        {reduceMotion ? (
          <Icon as={SvgLoader} size={16} className="text-status-info-05" />
        ) : (
          <Spinner size={16} className="text-status-info-05" />
        )}
        <Text font="main-ui-muted" color="text-04" className="flex-1">
          {header}
        </Text>
      </View>
      <View className="gap-16 px-12 pb-8">
        {pageCount > 1 ? (
          <Text
            font="secondary-body"
            color="text-03"
            accessibilityLiveRegion="polite"
            accessibilityLabel={`Question ${page + 1} of ${pageCount}`}
          >
            {`Question ${page + 1} of ${pageCount}`}
          </Text>
        ) : null}
        <View
          key={item.id}
          accessibilityRole={item.multi_select ? undefined : "radiogroup"}
          accessibilityLabel={item.question}
          className="gap-6"
        >
          <Text font="secondary-action" color="text-03">
            {item.header}
          </Text>
          <Text font="main-ui-body" color="text-05">
            {item.question}
          </Text>
          {item.multi_select ? (
            <Text font="secondary-body" color="text-03">
              Choose all that apply.
            </Text>
          ) : null}
          {item.options.map((option, index) => (
            <OptionRow
              key={index}
              option={option}
              multiSelect={item.multi_select}
              selected={choice.labels.includes(option.label)}
              disabled={submitting}
              onPress={() => chooseOption(option.label)}
            />
          ))}
          <OptionRow
            option={OTHER}
            multiSelect={item.multi_select}
            selected={choice.other}
            disabled={submitting}
            onPress={() =>
              choose(
                item.multi_select
                  ? { ...choice, other: !choice.other }
                  : { labels: [], other: true },
              )
            }
          />
          {choice.other ? (
            <TextInput
              value={notes.get(item.id) ?? ""}
              onChangeText={(text) =>
                setNotes((current) => new Map(current).set(item.id, text))
              }
              placeholder="Your answer"
              accessibilityLabel={`Your answer: ${item.header}`}
              autoFocus
            />
          ) : null}
        </View>
        {submitHint !== null ? (
          <Text font="secondary-body" color="text-03">
            {submitHint}
          </Text>
        ) : null}
        {error !== null ? (
          <Text
            font="secondary-body"
            color="status-error-05"
            accessibilityLiveRegion="assertive"
          >
            {error}
          </Text>
        ) : null}
      </View>
      <View className="flex-row items-center justify-end px-12 pb-12 pt-4">
        {pageCount > 1 ? (
          <Button
            prominence="tertiary"
            size="md"
            disabled={submitting || page === 0}
            onPress={() => goToPage(page - 1)}
            accessibilityLabel="Back to the previous question"
            className="mr-8"
          >
            Back
          </Button>
        ) : null}
        {lastPage ? (
          <Button
            prominence="primary"
            size="md"
            disabled={submitting || answers === null}
            onPress={() => {
              if (answers !== null) void submit(answers);
            }}
            accessibilityLabel="Submit your answers"
            accessibilityHint={submitHint ?? undefined}
          >
            Submit
          </Button>
        ) : (
          <Button
            prominence="primary"
            size="md"
            onPress={() => goToPage(page + 1)}
            accessibilityLabel="Next question"
          >
            Next
          </Button>
        )}
      </View>
    </View>
  );
}

// Questions rebuild on every streamed packet; the request and resolution stay the same until a
// change.
export const ToolQuestionCard = memo(
  ToolQuestionCardComponent,
  (prev, next) =>
    prev.question.request === next.question.request &&
    prev.question.resolution === next.question.resolution &&
    prev.showsTypedAnswer === next.showsTypedAnswer,
);
