"use client";

import { useNavigation, useSearchParams } from "@opal/navigation";
import {
  type AnimationEvent,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getConfiguredSources } from "@/lib/connectors/utils";
import type { OnSubmitProps } from "@/hooks/useChatController";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { PacketType } from "@/app/app/services/streamingModels";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useTags } from "@/lib/searchFilters/hooks";
import { normalizeSourceSelection } from "@/lib/searchFilters/utils";
import {
  flushToolOptions,
  type ToolConfigurationHandle,
} from "@/lib/tools/hooks";

import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { useShallow } from "zustand/react/shallow";
import { toast } from "@opal/layouts";
import { prefersReducedMotion } from "@opal/utils";
import {
  errorHandlingFetcher,
  errorHandlingFetchWith,
  fetchErrorDetail,
  FetchError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import {
  followChatStream,
  refreshChatSession,
} from "@/lib/chat/settleChatSession";
import {
  readChatSessionStatus,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";
import { postQuestionAnswers } from "@/lib/chat/svc";
import { requestMentions } from "@/lib/chat/mentions";
import type {
  ChatSessionQueue,
  ChatSessionStatus,
  ChatSubagent,
  ChatSubagents,
  ComposedMessage,
  Mention,
  PendingChatMessage,
} from "@/lib/chat/types";
import {
  getLatestMessageChain,
  getMessageByMessageId,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import { getUnresolvedMultiModelTurn } from "@/lib/timeline/chat/message/multiModel";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useChatSessionStore,
  useCurrentChatState,
  useCurrentMessageTree,
} from "@/app/app/stores/useChatSessionStore";
import {
  type ChatArtifactFile,
  chatPublishedFiles,
  type LoadedPublishedFiles,
  parseArtifactLink,
} from "@/lib/chat/publishedFiles";
import {
  awaitsDecision,
  type AwaitingUser,
  readToolApprovals,
  readToolQuestions,
  readWaitingQuestions,
  readWaitingToolRequests,
  type ToolRequestRecord,
  toolApprovalStatus,
  toolQuestionStatus,
  useToolRequestUi,
  type WaitingToolRequest,
} from "@/lib/chat/toolApprovals";
import type {
  Packet,
  PublishedFile,
  StreamCursor,
} from "@/app/app/services/streamingModels";
import { processRawChatHistory } from "@/app/app/services/lib";
import { handleSSEStream } from "@/lib/search/streamingUtils";
import { SubagentPathContext } from "@/lib/chat/subagents";
import {
  APPROVAL_PENDING_ERROR_CODE,
  type BackendMessage,
  type ChatSession,
  type ChatStream,
  type Message,
} from "@/app/app/types";
import {
  exportChatSession,
  type ChatExportFormat,
} from "@/lib/chat/exportChatSession";
import { UNNAMED_CHAT } from "@/lib/constants";
import type { DropdownAction } from "@opal/components";
import { SvgChevronLeft, SvgDownload, SvgFileText, SvgHash } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  type ChatRunStatus,
  endedRunStatus,
  isWorking,
  liveRunStatus,
  useUnseenRuns,
} from "@/lib/chat/runStatus";

const EMPTY_PENDING_MESSAGES: PendingChatMessage[] = [];
const SERVER_WORK_POLL_MS = 2000;

/** The response new input continues. Without a saved ID the server targets the running one. */
function pendingInputTarget(tree: MessageTreeState | undefined) {
  if (!tree) return { needsResponseSelection: false, targetResponseId: null };
  const history = getLatestMessageChain(tree);
  const needsResponseSelection = Boolean(
    getUnresolvedMultiModelTurn(history, tree)
  );
  const latest = history.at(-1);
  return {
    needsResponseSelection,
    targetResponseId:
      latest?.type === "assistant" &&
      latest.messageId != null &&
      latest.messageId > 0 &&
      !needsResponseSelection
        ? latest.messageId
        : null,
  };
}

/** Whether the server refused input because the chat waits for the user:
 * a tool approval or answers to questions. */
function isApprovalPendingError(error: unknown): boolean {
  return (
    error instanceof FetchError &&
    error.info?.error_code === APPROVAL_PENDING_ERROR_CODE
  );
}

export interface ResponseToolRequests {
  /** Requests and questions that wait no more, as records in the reply's
   * timeline. */
  records: ToolRequestRecord[];
  /** What the reply's own requests wait for from this user, if anything. */
  awaiting: AwaitingUser | null;
}

/**
 * The approval requests and questions of one response, as its timeline
 * shows them. Cards that wait for the user show in the transcript's trailing
 * regions.
 */
export function useToolRequests(rawPackets: Packet[]): ResponseToolRequests {
  const approvals = readToolApprovals(rawPackets).entries;
  const questions = readToolQuestions(rawPackets).entries;
  // Only this response's statuses, so other decisions do not re-render it.
  const localStatuses = useToolRequestUi(
    useShallow((state) =>
      approvals.map((entry) =>
        state.localStatuses.get(entry.request.approval_id)
      )
    )
  );
  const localAnswers = useToolRequestUi(
    useShallow((state) =>
      questions.map((entry) =>
        state.localAnswers.get(entry.request.question_request_id)
      )
    )
  );
  const resolvedIds = [
    ...approvals
      .filter((entry) => entry.outcome !== null)
      .map((entry) => entry.request.approval_id),
    ...questions
      .filter((entry) => entry.resolution !== null)
      .map((entry) => entry.request.question_request_id),
  ].join(" ");
  useEffect(() => {
    if (resolvedIds)
      useToolRequestUi.getState().forgetStatuses(resolvedIds.split(" "));
  }, [resolvedIds]);
  return useMemo(() => {
    const records: ToolRequestRecord[] = [];
    let awaitingApproval = false;
    let awaitingAnswer = false;
    approvals.forEach((entry, index) => {
      const status = toolApprovalStatus(entry, localStatuses[index]);
      if (!awaitsDecision(entry))
        records.push({
          kind: "approval",
          turnIndex: entry.turnIndex,
          request: entry.request,
          status,
        });
      else if (entry.request.agent_name === null && status === "pending")
        awaitingApproval = true;
    });
    questions.forEach((entry, index) => {
      const status = toolQuestionStatus(entry, localAnswers[index]);
      if (entry.resolution !== null)
        records.push({
          kind: "question",
          turnIndex: entry.turnIndex,
          request: entry.request,
          status,
        });
      else if (status.kind === "pending") awaitingAnswer = true;
    });
    return {
      records,
      awaiting: awaitingApproval
        ? "approval"
        : awaitingAnswer
          ? "answer"
          : null,
    };
  }, [approvals, questions, localStatuses, localAnswers]);
}

/**
 * Brings a waiting card into view and shakes it when a blocked send points
 * the user at it. Clearing the nudge keeps a remounted card from repeating
 * it.
 */
export function useNudgedCard(requestId: string) {
  const nudge = useToolRequestUi((state) =>
    state.nudge?.requestId === requestId ? state.nudge.seq : null
  );
  const ref = useRef<HTMLDivElement>(null);
  const [shaking, setShaking] = useState(false);
  useEffect(() => {
    if (nudge === null) return;
    useToolRequestUi.getState().clearNudge(nudge);
    ref.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "center",
    });
    // Restart a shake that is still running.
    setShaking(false);
    requestAnimationFrame(() => setShaking(true));
  }, [nudge]);
  return {
    ref,
    shaking,
    onAnimationEnd: (event: AnimationEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) setShaking(false);
    },
  };
}

/**
 * Shows why the server refused input: a reply waits for a tool approval or
 * for answers to its questions. Callers keep the draft. The reply's first
 * waiting card, of `kind` when given, comes into view. An idle chat that
 * shows no such card loads the server's cards; a busy chat gets them from
 * its reader or its settlement.
 */
export function useShowPendingRequest(): (
  kind?: WaitingToolRequest["kind"]
) => void {
  const t = useTranslations("chat.input");
  const tReadiness = useTranslations("chat.readiness");
  return useCallback(
    (kind) => {
      const { currentSessionId, sessions } = useChatSessionStore.getState();
      const session = currentSessionId ? sessions.get(currentSessionId) : null;
      // A background subagent's request does not block input, and a
      // question that this client answered waits only for its resolution.
      const { localAnswers } = useToolRequestUi.getState();
      const approval =
        kind === "question" || !session
          ? undefined
          : readWaitingToolRequests(session.messageTree).flatMap((item) =>
              item.kind === "approval" && item.request.agent_name === null
                ? [item.request]
                : []
            )[0];
      const question =
        kind === "approval" || !session
          ? undefined
          : readWaitingQuestions(session.messageTree, localAnswers).find(
              (item) => item.status.kind === "pending"
            );
      toast.warning(
        t(
          approval
            ? "pendingToolApproval.toast"
            : question
              ? "pendingToolQuestion.toast"
              : "pendingUserInput.toast"
        )
      );
      if (!currentSessionId || !session) return;
      const requestId =
        approval?.approval_id ?? question?.request.question_request_id;
      if (requestId) useToolRequestUi.getState().nudgeRequest(requestId);
      else if (session.chatState === "input")
        void refreshChatSession(currentSessionId, tReadiness("checkFailed"));
    },
    [t, tReadiness]
  );
}

/**
 * Follows the response that the user's approval decision or answer
 * continues.
 *
 * `continued` follows the stream that the server names as the continuation.
 * Without one, the response continues in a later turn or in a live reader,
 * or an agent continues in the background: a status read hands the chat to
 * its status subscriber, which follows server turns until the chat is idle
 * and then loads the saved session. Incognito does not follow server turns
 * from its status: it waits for the next stream and follows it when it
 * writes its answers. A continuation that already ended is read from the
 * saved answer through a refresh.
 *
 * `refused` handles a 409 or 404: the request no longer waits, and another
 * decision or answer can have started the continuation. The status read
 * also reaches the status subscriber.
 */
export function useFollowUserInput() {
  const tReadiness = useTranslations("chat.readiness");
  const { mutate } = useSWRConfig();
  return useMemo(() => {
    const checkFailed = tReadiness("checkFailed");
    return {
      continued: async (sessionId: string, continuation: ChatStream | null) => {
        if (continuation) {
          followChatStream(sessionId, continuation, checkFailed);
          return;
        }
        if (
          !useChatSessionStore.getState().sessions.get(sessionId)?.incognito
        ) {
          void mutate(SWR_KEYS.chatSessionStatus(sessionId));
          return;
        }
        const next = await waitForChatResponseEnd(sessionId);
        if (next) followChatStream(sessionId, next, checkFailed);
        else await refreshChatSession(sessionId, checkFailed);
      },
      refused: async (sessionId: string) => {
        const status = await readChatSessionStatus(sessionId);
        if (status.is_processing && status.current_stream)
          followChatStream(sessionId, status.current_stream, checkFailed);
      },
    };
  }, [tReadiness, mutate]);
}

/** Whether the request no longer waits: the server answers 409 or 404. */
export function isClosedRequestError(error: unknown): boolean {
  return (
    error instanceof FetchError &&
    (error.status === 409 || error.status === 404)
  );
}

/**
 * The questions on the selected branch that wait for the user's answer, by
 * request ID, oldest first. A typed message answers them all: it goes to the
 * first, and the server answers every question of its response that waits.
 * They wait also while a foreground part of their response still runs.
 */
export function useWaitingQuestionIds(): string[] {
  const tree = useCurrentMessageTree();
  const localAnswers = useToolRequestUi((state) => state.localAnswers);
  const ids = useMemo(
    () =>
      tree
        ? readWaitingQuestions(tree, localAnswers)
            .filter((item) => item.status.kind === "pending")
            .map((item) => item.request.question_request_id)
            .join(" ")
        : "",
    [tree, localAnswers]
  );
  // A string key keeps the same list while the tree streams.
  return useMemo(() => (ids ? ids.split(" ") : []), [ids]);
}

export type JumpToLatestReason = "approval" | "question" | "newAnswer";

/**
 * Why the user should return to the end of the chat while the
 * scroll-to-bottom button shows (`visible`): an approval or a question
 * waits, or a run that went on after the button appeared has ended with new
 * output. Output that only loads, such as an opened chat's history, is not
 * new.
 */
export function useJumpToLatestReason(
  visible: boolean
): JumpToLatestReason | null {
  const tree = useCurrentMessageTree();
  const chatState = useCurrentChatState();
  const localStatuses = useToolRequestUi((state) => state.localStatuses);
  const waitingQuestionIds = useWaitingQuestionIds();
  const approvalWaits = useMemo(
    () =>
      tree
        ? readWaitingToolRequests(tree).some(
            (item) =>
              item.kind === "approval" &&
              !localStatuses.has(item.request.approval_id)
          )
        : false,
    [tree, localStatuses]
  );
  const contentKey = useMemo(() => {
    if (!tree) return "";
    const chain = getLatestMessageChain(tree);
    const last = chain[chain.length - 1];
    const visiblePackets =
      last?.packets.filter(({ obj }) => obj.type !== PacketType.STOP).length ??
      0;
    return `${chain.length}:${visiblePackets}`;
  }, [tree]);
  const sessionId = useChatSessionStore((state) => state.currentSessionId);
  const running = chatState === "loading" || chatState === "streaming";
  // The content when the button last appeared or went away, and whether a
  // run went on since.
  const [seen, setSeen] = useState({
    visible,
    sessionId,
    contentKey,
    ran: false,
  });
  if (seen.visible !== visible || seen.sessionId !== sessionId)
    setSeen({ visible, sessionId, contentKey, ran: false });
  else if (visible && running && !seen.ran) setSeen({ ...seen, ran: true });

  if (!visible) return null;
  if (approvalWaits) return "approval";
  if (waitingQuestionIds.length > 0) return "question";
  if (chatState === "input" && seen.ran && seen.contentKey !== contentKey)
    return "newAnswer";
  return null;
}

/**
 * Sends text that the user typed as the answer to the waiting questions,
 * and follows the response that it continues. The questions show as
 * answered until their resolution arrives. Resolves to false when the
 * server did not take the text, so the caller keeps it as a draft.
 */
export function useAnswerWithMessage(): (
  questionRequestIds: string[],
  message: string
) => Promise<boolean> {
  const t = useTranslations("chat.messages.toolQuestion");
  const showPendingRequest = useShowPendingRequest();
  const follow = useFollowUserInput();
  return useCallback(
    async (questionRequestIds, message) => {
      const sessionId = useChatSessionStore.getState().currentSessionId;
      const [first] = questionRequestIds;
      if (sessionId === null || first === undefined) return false;
      const { recordAnswer } = useToolRequestUi.getState();
      try {
        const response = await postQuestionAnswers(first, { message });
        for (const id of questionRequestIds)
          recordAnswer(id, { kind: "answered", answers: null, message });
        void follow.continued(sessionId, response.continuation);
        return true;
      } catch (cause) {
        if (isApprovalPendingError(cause)) {
          // An approval of the same response still waits.
          showPendingRequest("approval");
        } else if (isClosedRequestError(cause)) {
          for (const id of questionRequestIds)
            recordAnswer(id, { kind: "closed" });
          void follow.refused(sessionId);
        } else {
          // Such as a rejection by the admin's query hook, or text that is
          // too long.
          toast.error(fetchErrorDetail(cause) ?? t("submitError"));
        }
        return false;
      }
    },
    [t, showPendingRequest, follow]
  );
}

/**
 * How often a chat's status reloads. Pending input and background work can
 * start a turn this client did not send; a decided agent request counts as
 * background work until its agent settles. Pass it in a new arrow on each
 * render: SWR reschedules its poll only when `refreshInterval` changes, so a
 * stable function reads only the data from before the first load.
 */
function statusPollInterval(current: ChatSessionStatus | undefined): number {
  return current?.has_startable_input || current?.has_active_subagents
    ? SERVER_WORK_POLL_MS
    : 0;
}

/**
 * Server-owned pending messages and background activity of the current chat.
 * Mount once per chat surface; the composer only renders the result.
 */
export function useChatSessionQueue(enabled: boolean): ChatSessionQueue {
  const t = useTranslations("chat.input.pendingMessages");
  const tReadiness = useTranslations("chat.readiness");
  // Primitives only: the message tree changes on every streamed frame.
  const {
    sessionId,
    idle,
    incognito,
    needsResponseSelection,
    loadedApprovalsVersion,
  } = useChatSessionStore(
    useShallow((state) => {
      const session = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)
        : undefined;
      const target = pendingInputTarget(session?.messageTree);
      return {
        sessionId: state.currentSessionId,
        idle: session?.chatState === "input" && !session.isFetchingChatMessages,
        incognito: session?.incognito ?? false,
        needsResponseSelection: target.needsResponseSelection,
        loadedApprovalsVersion: session?.approvalsVersion,
      };
    })
  );
  const pendingKey =
    enabled && sessionId ? SWR_KEYS.pendingChatMessages(sessionId) : null;
  // An incognito chat has no server queue, but its background agents' requests
  // still arrive through its status.
  const statusKey =
    (enabled || incognito) && sessionId
      ? SWR_KEYS.chatSessionStatus(sessionId)
      : null;

  // Key-addressed, unlike the mutate useSWR returns, which follows the current key.
  const { mutate } = useSWRConfig();
  const { data: messages, error } = useSWR<PendingChatMessage[], Error>(
    pendingKey,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  const { data: status } = useSWR<ChatSessionStatus, Error>(
    statusKey,
    errorHandlingFetcher,
    {
      refreshInterval: (current) => statusPollInterval(current),
      onErrorRetry: skipRetryOnAuthError,
    }
  );

  // A reader owns a busy session; an idle one attaches to turns the server
  // started, whichever status read found them.
  const checkFailed = tReadiness("checkFailed");
  useEffect(() => {
    if (!sessionId || !status || !idle) return;
    const session = useChatSessionStore.getState().sessions.get(sessionId);
    if (!session) return;
    const missingResponse =
      status.latest_response_id !== null &&
      !getMessageByMessageId(session.messageTree, status.latest_response_id);
    if (status.is_processing || missingResponse)
      void refreshChatSession(sessionId, checkFailed);
  }, [sessionId, status, idle, checkFailed]);

  // Background agents' requests and their resolutions arrive only through a
  // load. A status version that differs from the loaded one refreshes. A chat
  // that this browser started loaded nothing, so it compares against the
  // empty version of a chat with no request: a clean send keeps its streamed
  // messages, and any request refreshes.
  const approvalsVersion = status?.approvals_version;
  useEffect(() => {
    if (!sessionId || approvalsVersion === undefined || !idle) return;
    if (approvalsVersion !== (loadedApprovalsVersion ?? ""))
      void refreshChatSession(sessionId, checkFailed);
  }, [sessionId, approvalsVersion, loadedApprovalsVersion, idle, checkFailed]);

  // Every turn saves a new response, so a new latest response means a turn
  // may have taken pending input, whoever started it and whether or not this
  // browser read its stream.
  const latestResponseId = status?.latest_response_id;
  const seenResponse = useRef<{
    sessionId: string | null;
    responseId: number | null | undefined;
  }>({ sessionId, responseId: latestResponseId });
  useEffect(() => {
    const previous = seenResponse.current;
    seenResponse.current = { sessionId, responseId: latestResponseId };
    if (
      pendingKey &&
      previous.sessionId === sessionId &&
      previous.responseId !== undefined &&
      latestResponseId !== undefined &&
      latestResponseId !== previous.responseId
    )
      void mutate(pendingKey);
  }, [sessionId, latestResponseId, pendingKey, mutate]);

  // One request per chat at a time. The composer keeps new input until it ends.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const busy = busyKey !== null && busyKey === pendingKey;
  const showPendingRequest = useShowPendingRequest();

  return useMemo(() => {
    // Any other 409 means the server already accepted the message.
    function toastPendingFailure(error: unknown, fallback: string) {
      if (isApprovalPendingError(error)) {
        showPendingRequest();
        return;
      }
      toast.error(
        error instanceof FetchError && error.status === 409
          ? t("alreadyAccepted")
          : (fetchErrorDetail(error) ?? fallback)
      );
    }

    // Writes after an await target the chat that made the request.
    async function request<T>(
      action: (key: string) => Promise<T>
    ): Promise<T | null> {
      const key = pendingKey;
      const status = statusKey;
      if (!key || !status || busy) return null;
      setBusyKey(key);
      try {
        return await action(key);
      } finally {
        setBusyKey((current) => (current === key ? null : current));
        // A write can make input startable, and only a fresh status polls for
        // the turn that takes it.
        void mutate(status);
      }
    }

    return {
      enabled,
      messages: messages ?? EMPTY_PENDING_MESSAGES,
      error: error ? t("loadFailed") : null,
      busy,
      needsResponseSelection,
      submit: async ({ message, mentions }, delivery, turn) =>
        (await request(async (key) => {
          const session = sessionId
            ? useChatSessionStore.getState().sessions.get(sessionId)
            : undefined;
          // A turn the server starts reads the chat's saved tools.
          if (sessionId) await flushToolOptions(sessionId);
          try {
            const accepted = await errorHandlingFetchWith<PendingChatMessage>(
              key,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  message,
                  delivery,
                  target_response_id: pendingInputTarget(session?.messageTree)
                    .targetResponseId,
                  deep_research: turn.deepResearch,
                  llm_override: turn.llmOverride,
                  mentions: requestMentions(mentions),
                }),
              }
            );
            // Revalidates after the write, since a turn can consume it at once.
            void mutate<PendingChatMessage[]>(key, (current = []) => [
              ...current,
              accepted,
            ]);
            return true;
          } catch (failure) {
            if (isApprovalPendingError(failure)) showPendingRequest();
            else toast.error(fetchErrorDetail(failure) ?? t("submitFailed"));
            return false;
          }
        })) ?? false,
      withdraw: (id) =>
        request(async (key) => {
          try {
            const withdrawn = await errorHandlingFetchWith<PendingChatMessage>(
              `${key}/${id}`,
              { method: "DELETE" }
            );
            void mutate<PendingChatMessage[]>(
              key,
              (current = []) => current.filter((message) => message.id !== id),
              { revalidate: false }
            );
            return withdrawn;
          } catch (failure) {
            toastPendingFailure(failure, t("withdrawFailed"));
            void mutate(key);
            return null;
          }
        }),
      interrupt: async (id) => {
        await request(async (key) => {
          if (sessionId) await flushToolOptions(sessionId);
          try {
            await errorHandlingFetchWith<PendingChatMessage>(
              `${key}/${id}/interrupt`,
              { method: "POST" }
            );
          } catch (failure) {
            toastPendingFailure(failure, t("interruptFailed"));
          } finally {
            void mutate(key);
          }
        });
      },
    };
  }, [
    enabled,
    messages,
    error,
    busy,
    needsResponseSelection,
    sessionId,
    pendingKey,
    statusKey,
    mutate,
    t,
    showPendingRequest,
  ]);
}

interface UseSendChatMessageFromURLProps {
  /** From `useChatController`, which needs more than this hook can see. */
  onSubmit: (props: OnSubmitProps) => void;
  /** Resolved against the active project, so the page decides it, not this. */
  deepResearch: boolean;
  /** Where the filters a URL names are written: the chat's own configuration. */
  toolConfiguration: ToolConfigurationHandle;
}

/**
 * Sends the message a URL asks for, scoped by the filters that URL names.
 *
 * A link into the app can carry both a prompt and a search scope —
 * `?sources=slack&user-prompt=…&send-on-load=true` — which is how the Chrome
 * extension, an agent preview, and a shared link all open a chat that is
 * already narrowed and already asking.
 *
 * Two arrivals are handled: the page loading with `send-on-load` set, and a
 * `PAGE_CHANGE` message posted by the extension while the page stays put.
 * Both queue the query rather than sending in place, because sending is
 * gated twice:
 *
 * 1. A query naming sources, sets or tags waits for that data to settle —
 *    resolving names against a list still in flight would scope the send
 *    wrong and persist that wrong scope on the chat. A fetch that errors
 *    counts as settled: its names match nothing, so that dimension falls
 *    back to unfiltered — the pre-refactor behavior — rather than the
 *    send waiting forever.
 * 2. The submit happens one render after the filters are written, so it
 *    reads the configuration it just scoped instead of the previous one.
 *
 * `send-on-load` is stripped from the URL afterwards, so a refresh does not
 * send the message a second time.
 *
 * Everything reachable from context is read here — the filters, the project's
 * files, and the sources, sets and tags a name resolves against. Only the
 * submit itself and the deep-research flag come from the caller, because
 * neither is context.
 */
export function useSendChatMessageFromURL({
  onSubmit,
  deepResearch,
  toolConfiguration,
}: UseSendChatMessageFromURLProps) {
  const navigation = useNavigation();
  const searchParams = useSearchParams();

  const {
    availableSources,
    isLoading: sourcesLoading,
    settled: sourcesSettled,
  } = useAvailableSources();

  const configuredSources = useMemo(
    () => getConfiguredSources(availableSources),
    [availableSources]
  );

  const [queuedQuery, setQueuedQueryState] = useState<string | null>(null);
  // The page that queued the query. The page being left stays mounted (and
  // hidden) while the next one renders, so a query that settles after the
  // user moved on must not write to the new page's URL or send.
  const queuedPathnameRef = useRef<string | null>(null);
  const setQueuedQuery = useCallback((query: string | null) => {
    queuedPathnameRef.current =
      query === null ? null : window.location.pathname;
    setQueuedQueryState(query);
  }, []);

  // What the queued query asks for. Names that match nothing available are
  // dropped later, so a stale or hand-typed link narrows the search rather
  // than failing it. URLSearchParams already percent-decoded the value;
  // decoding again would corrupt names and throw on a legitimate literal
  // like "100%".
  const queuedRequest = useMemo(() => {
    const params = new URLSearchParams(queuedQuery ?? "");
    const namesIn = (param: string): string[] =>
      params.get(param)?.split(",") ?? [];
    const from = new Date(params.get("from") ?? "");
    const to = new Date(params.get("to") ?? "");
    return {
      message: params.get(SEARCH_PARAM_NAMES.USER_PROMPT),
      sources: namesIn("sources"),
      documentSets: namesIn("documentSets"),
      tags: namesIn("tags"),
      skills: namesIn(SEARCH_PARAM_NAMES.SKILLS),
      // A search sends only the start of a range.
      rangeFrom:
        !isNaN(from.getTime()) && !isNaN(to.getTime())
          ? from.toISOString()
          : null,
    };
  }, [queuedQuery]);

  // Sets and tags are fetched only for a queued query that names them.
  const { documentSets, isLoading: documentSetsLoading } = useDocumentSets(
    queuedRequest.documentSets.length > 0
  );
  const { tags, isLoading: tagsLoading } = useTags(
    queuedRequest.tags.length > 0
  );

  const [pendingMessage, setPendingMessage] = useState<ComposedMessage | null>(
    null
  );

  // Arriving with the parameters already on the URL.
  //
  // Guarded because `navigation.go` only drops `send-on-load` a tick after
  // the query is processed — without this the effect re-runs inside that
  // window and queues the same prompt twice.
  const sentForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) return;
    const query = searchParams.toString();
    if (sentForRef.current === query) return;
    sentForRef.current = query;
    setQueuedQuery(query);
  }, [searchParams, setQueuedQuery]);

  // The extension navigating the embedded page without a reload.
  useEffect(() => {
    function onPageChange(event: MessageEvent) {
      // Only the extension that embeds the page may send prompts: a frame
      // inside it, such as an HTML file preview, must not
      if (window.parent === window || event.source !== window.parent) return;
      if (!/^(chrome|moz)-extension:\/\//.test(event.origin)) return;
      if (event.data?.type !== SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) return;
      try {
        setQueuedQuery(new URL(event.data.href).searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }

    window.addEventListener("message", onPageChange);
    return () => window.removeEventListener("message", onPageChange);
  }, [setQueuedQuery]);

  // Processes the queued query once every dimension it names has settled.
  // Re-runs as the loading flags flip, so a query that arrived early waits
  // here instead of resolving names against half-fetched lists.
  useEffect(() => {
    if (queuedQuery === null) return;
    if (window.location.pathname !== queuedPathnameRef.current) {
      // Not handled, so the same URL can queue it again on a return.
      sentForRef.current = null;
      setQueuedQuery(null);
      return;
    }
    // Writes are dropped until the composer's configuration binds to its
    // chat, so processing earlier would scope nothing and persist nothing.
    if (!toolConfiguration.ready) return;

    if (
      (queuedRequest.sources.length > 0 && sourcesLoading) ||
      (queuedRequest.documentSets.length > 0 && documentSetsLoading) ||
      (queuedRequest.tags.length > 0 && tagsLoading)
    ) {
      return;
    }
    setQueuedQuery(null);

    // Only the dimensions the URL names are written; the rest keep what the
    // chat already holds — an agent-viewer hand-off arrives with picks this
    // must not clear. A failed source fetch also leaves sources untouched:
    // writing a selection derived from a partial list would persist a wrong
    // scope, where one wide send does not.
    toolConfiguration.setFilters((current) => ({
      selectedSources:
        queuedRequest.sources.length > 0 && sourcesSettled
          ? normalizeSourceSelection(
              configuredSources
                .filter((source) =>
                  queuedRequest.sources.includes(source.internalName)
                )
                .map((source) => source.uniqueKey),
              configuredSources.map((source) => source.uniqueKey)
            )
          : current.selectedSources,
      documentSets:
        queuedRequest.documentSets.length > 0
          ? documentSets
              .map((ds) => ds.name)
              .filter((name) => queuedRequest.documentSets.includes(name))
          : current.documentSets,
      tags:
        queuedRequest.tags.length > 0
          ? tags.filter((tag) => queuedRequest.tags.includes(tag.tag_value))
          : current.tags,
      timeRange:
        queuedRequest.rangeFrom !== null
          ? { from: queuedRequest.rangeFrom }
          : current.timeRange,
    }));

    // Dropped before the replace so a refresh does not resend.
    const params = new URLSearchParams(queuedQuery);
    params.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);
    navigation.go(`?${params.toString()}`, { replace: true, scroll: false });

    if (queuedRequest.message)
      setPendingMessage({
        message: queuedRequest.message,
        mentions: queuedRequest.skills.map(
          (name): Mention => ({ type: "skill", name })
        ),
      });
  }, [
    queuedQuery,
    queuedRequest,
    sourcesLoading,
    sourcesSettled,
    documentSetsLoading,
    tagsLoading,
    configuredSources,
    documentSets,
    tags,
    navigation,
    toolConfiguration,
    setQueuedQuery,
  ]);

  // Submits one render after the filter write above landed, so `onSubmit`'s
  // closure reads the configuration the query scoped, not the previous one.
  useEffect(() => {
    if (pendingMessage === null) return;
    setPendingMessage(null);
    onSubmit({
      ...pendingMessage,
      currentMessageFiles: [],
      deepResearch,
    });
  }, [pendingMessage, onSubmit, deepResearch]);
}

// A chat's loads of its file list and its message tree
export interface PublishedFilesSource {
  sessionId: string;
  loadedPublishedFiles: LoadedPublishedFiles;
  messageTree: MessageTreeState;
}

const NO_PUBLISHED_FILES: PublishedFile[] = [];
// The files of each message tree, keyed by the loads they came from
const publishedFilesByTree = new WeakMap<
  MessageTreeState,
  { loaded: LoadedPublishedFiles; files: PublishedFile[] }
>();

/**
 * The files the model published in a chat (`chatPublishedFiles`), built once
 * per message tree and loads.
 */
export function publishedFilesOf(
  source: PublishedFilesSource | undefined | null
): PublishedFile[] {
  if (!source) return NO_PUBLISHED_FILES;
  const { sessionId, loadedPublishedFiles: loaded, messageTree } = source;
  const cached = publishedFilesByTree.get(messageTree);
  if (cached && cached.loaded === loaded) return cached.files;
  const files = chatPublishedFiles(loaded, messageTree, sessionId);
  publishedFilesByTree.set(messageTree, { loaded, files });
  return files;
}

const NO_SUBAGENTS: ChatSubagent[] = [];

/** The most agents the agents endpoint returns: the backend's
 * `MAX_DISCOVERED_AGENTS` (onyx/chat/models.py). */
export const MAX_LISTED_SUBAGENTS = 128;

/**
 * The chat's background agents, by the newest response that started them,
 * and `stopAgent`, which stops one agent and the agents below it. They load
 * once the chat's status does, again when it changes whether agents are
 * active or which response is newest, and poll while agents are active. The
 * status polls as the queue's does, also for chats without a queue, and while
 * a reply streams (`streaming`), which can start agents. `loaded` turns true
 * once a list has been read from the server since the hook mounted.
 */
export function useChatSubagents(
  sessionId: string | null,
  streaming: boolean
): ChatSubagents {
  const t = useTranslations("chat.activity.agents");
  const { data: status, mutate: reloadStatus } = useSWR<
    ChatSessionStatus,
    Error
  >(
    sessionId ? SWR_KEYS.chatSessionStatus(sessionId) : null,
    errorHandlingFetcher,
    {
      // A number while a reply streams: each streamed packet renders the
      // caller again, and a new function would restart SWR's timer
      refreshInterval: streaming
        ? SERVER_WORK_POLL_MS
        : (current) => statusPollInterval(current),
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  const active = status?.has_active_subagents ?? false;
  const url = sessionId ? SWR_KEYS.chatSessionAgents(sessionId) : "";
  const {
    data,
    error,
    isValidating,
    mutate: reloadAgents,
  } = useSWR<ChatSubagent[], Error>(
    status && sessionId ? [url, active, status.latest_response_id] : null,
    () => errorHandlingFetcher<ChatSubagent[]>(url),
    {
      refreshInterval: active ? SERVER_WORK_POLL_MS : 0,
      keepPreviousData: true,
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  // A cached list from an earlier visit is stale until a read here succeeds;
  // SWR keeps the cached list after a failed read.
  const [loaded, setLoaded] = useState(false);
  if (!loaded && data !== undefined && !isValidating && error === undefined) {
    setLoaded(true);
  }
  const stopAgent = useCallback(
    async (agentId: string) => {
      if (!sessionId) return;
      try {
        await errorHandlingFetchWith<unknown>(
          `/api/chat/chat-session/${sessionId}/stop-subagents`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_id: agentId }),
          }
        );
      } catch (failure) {
        toast.error(fetchErrorDetail(failure) ?? t("stopFailed"));
      } finally {
        void reloadStatus();
        void reloadAgents();
      }
    },
    [sessionId, t, reloadStatus, reloadAgents]
  );
  return {
    agents: data ?? NO_SUBAGENTS,
    loaded,
    stopAgent,
  };
}

/**
 * Opens, with `openFile`, the artifact version that the URL names
 * (SEARCH_PARAM_NAMES.ARTIFACT_ID and ARTIFACT_VERSION, which the artifact
 * link page sets) once its chat is `loadedChatId`, the chat that the page
 * shows and has loaded, then drops the parameters so a reload does not open
 * it again. A URL that names a version pins the file's tab to it.
 */
export function useOpenArtifactFromUrl(
  loadedChatId: string | null,
  openFile: (file: PublishedFile, pinVersion: boolean) => void
): void {
  const searchParams = useSearchParams();
  const navigation = useNavigation();
  const artifactId = searchParams?.get(SEARCH_PARAM_NAMES.ARTIFACT_ID);
  const version = searchParams?.get(SEARCH_PARAM_NAMES.ARTIFACT_VERSION);
  // Read as the link that sets them, so only a UUID and a whole version
  // number reach the request URL.
  const link = artifactId
    ? parseArtifactLink(
        `/app/artifacts/${artifactId}${version ? `/v${version}` : ""}`
      )
    : null;
  const {
    data: file,
    error,
    isValidating,
  } = useSWR<ChatArtifactFile, Error>(
    link ? SWR_KEYS.chatArtifact(link.artifactId, link.version) : null,
    errorHandlingFetcher
  );
  const pinVersion = link?.version != null;
  useEffect(() => {
    // A cached response of an earlier visit can name an older version, or a
    // file that is gone, which SWR keeps when its reload fails
    if (
      !file ||
      isValidating ||
      error ||
      file.chat_id !== loadedChatId ||
      !searchParams
    )
      return;
    openFile(file, pinVersion);
    const params = new URLSearchParams(searchParams.toString());
    params.delete(SEARCH_PARAM_NAMES.ARTIFACT_ID);
    params.delete(SEARCH_PARAM_NAMES.ARTIFACT_VERSION);
    navigation.go(`?${params.toString()}`, { replace: true, scroll: false });
  }, [
    file,
    error,
    isValidating,
    pinVersion,
    loadedChatId,
    openFile,
    searchParams,
    navigation,
  ]);
}

/**
 * The files the model published in a chat: the open chat in the store, or a
 * chat that the page holds, such as a shared chat. The array stays the same
 * while its content does, so a packet that publishes nothing re-renders
 * nothing.
 */
export function usePublishedFiles(
  chat: "current" | PublishedFilesSource | null
): PublishedFile[] {
  return useChatSessionStore(
    useShallow((state) =>
      publishedFilesOf(
        chat === "current"
          ? state.sessions.get(state.currentSessionId ?? "")
          : chat
      )
    )
  );
}

export interface ChatExportMenu {
  /** One row per format, for a menu that lists the formats itself. */
  exportItems: DropdownAction[];
  /** An "Export As…" row that opens the formats in a view of their own. */
  exportMenuItem: DropdownAction;
}

interface ChatExportOption {
  format: ChatExportFormat;
  icon: IconFunctionComponent;
  /** The row's title in a menu that lists the formats itself. */
  title: string;
  /** The row's title in the "Export As…" view. */
  viewTitle: string;
}

/**
 * Menu rows that download a chat's transcript. A failed export shows a toast.
 * Without a session the rows do nothing.
 */
export function useChatExportMenu(
  chatSession: ChatSession | null
): ChatExportMenu {
  const t = useTranslations("chat.export");

  async function exportAs(format: ChatExportFormat) {
    if (!chatSession) return;
    try {
      await exportChatSession(
        chatSession.id,
        chatSession.name || UNNAMED_CHAT,
        format
      );
    } catch (error) {
      console.error("Failed to export chat:", error);
      toast.error(t("failed.message"));
    }
  }

  const options: ChatExportOption[] = [
    {
      format: "markdown",
      icon: SvgHash,
      title: t("asMarkdown.label"),
      viewTitle: t("markdown.label"),
    },
    {
      format: "text",
      icon: SvgFileText,
      title: t("asPlaintext.label"),
      viewTitle: t("plaintext.label"),
    },
  ];

  return {
    exportItems: options.map(
      ({ format, icon, title }): DropdownAction => ({
        kind: "action",
        id: `export-${format}`,
        icon,
        title,
        onSelect: () => void exportAs(format),
      })
    ),
    exportMenuItem: {
      kind: "action",
      id: "export",
      icon: SvgDownload,
      title: t("menu.label"),
      onSelect: (views) =>
        views.push({
          key: "export",
          items: [
            {
              kind: "action",
              id: "back",
              icon: SvgChevronLeft,
              title: t("menu.label"),
              onSelect: (backViews) => backViews.pop(),
            },
            ...options.map(
              ({ format, icon, viewTitle }): DropdownAction => ({
                kind: "action",
                id: `export-${format}`,
                icon,
                title: viewTitle,
                onSelect: () => void exportAs(format),
              })
            ),
          ],
        }),
    },
  };
}

/** The run status that a chat's sidebar row shows. */
export function useChatRunStatus(sessionId: string): ChatRunStatus | null {
  const localStatuses = useToolRequestUi((state) => state.localStatuses);
  const localAnswers = useToolRequestUi((state) => state.localAnswers);
  const session = useChatSessionStore((state) => state.sessions.get(sessionId));
  const live = useMemo(
    () =>
      session ? liveRunStatus(session, localStatuses, localAnswers) : null,
    [session, localStatuses, localAnswers]
  );
  const unseen = useUnseenRuns((state) => state.unseen.get(sessionId) ?? null);
  return live ?? unseen;
}

/**
 * Records how runs end while their chat is not on screen, and clears that
 * record when the user opens the chat. Mount once, in the app sidebar.
 */
export function useTrackChatRuns(): void {
  const visibleChatId = useAppPosition().chat();
  const visibleChatIdRef = useRef(visibleChatId);

  useEffect(() => {
    visibleChatIdRef.current = visibleChatId;
    if (visibleChatId) useUnseenRuns.getState().markSeen(visibleChatId);
  }, [visibleChatId]);

  useEffect(
    () =>
      useChatSessionStore.subscribe((state, prev) => {
        if (state.sessions === prev.sessions) return;
        for (const [sessionId, session] of state.sessions) {
          const before = prev.sessions.get(sessionId);
          if (
            !before ||
            before === session ||
            session.incognito ||
            session.runMarkerSuppressed ||
            !isWorking(before) ||
            isWorking(session) ||
            sessionId === visibleChatIdRef.current
          )
            continue;
          const ended = endedRunStatus(session);
          if (ended === "failed" || ended === "done")
            useUnseenRuns.getState().markUnseen(sessionId, ended);
        }
      }),
    []
  );
}

/** A background agent's saved conversation, with its live stream. */
interface SubagentHistory {
  messages: BackendMessage[];
  packets: Packet[][];
  stream: { stream_id: number; response_ids: number[] } | null;
}

interface SpawnedSubagents {
  /** The agent for each name; undefined for an empty or unlisted name. */
  agents: (ChatSubagent | undefined)[];
  /**
   * The chat has an agents list. Without one (such as a shared chat), an
   * undefined agent is unknown, not starting. While the list loads, a spawn
   * still counts as starting, so a running group does not flash done.
   */
  available: boolean;
  /**
   * The list is not cut off at the endpoint's cap, so an agent it lacks has
   * not started yet. In a full list, an older agent can be missing.
   */
  complete: boolean;
}

/**
 * The open chat's agents that the rendering agent spawned with these names,
 * once the agents list holds them.
 */
export function useSpawnedSubagents(
  names: readonly string[]
): SpawnedSubagents {
  const base = useContext(SubagentPathContext);
  const sessionId = useChatSessionStore((state) => state.currentSessionId);
  const { agents } = useChatSubagents(sessionId, false);
  return {
    agents: names.map((name) =>
      name
        ? agents.find((agent) => agent.path === `${base}/${name}`)
        : undefined
    ),
    available: sessionId !== null,
    complete: agents.length < MAX_LISTED_SUBAGENTS,
  };
}

function isPacket(item: Packet | StreamCursor): item is Packet {
  return "obj" in item;
}

async function* followSubagentStream(
  sessionId: string,
  agentId: string,
  streamId: number,
  cursor: number,
  signal: AbortSignal
): AsyncGenerator<Packet | StreamCursor, void, unknown> {
  const response = await fetch(
    `/api/chat/chat-session/${sessionId}/agents/${agentId}/stream?stream_id=${streamId}&cursor=${cursor}`,
    { signal }
  );
  if (!response.ok)
    throw new FetchError(
      `HTTP error! status: ${response.status}`,
      response.status,
      null
    );
  yield* handleSSEStream<Packet | StreamCursor>(response, signal);
}

const RECONNECT_DELAY_MS = 1000;

interface SubagentTranscript {
  /** The conversation's messages, oldest first. */
  messages: Message[];
  loading: boolean;
  failed: boolean;
}

/**
 * A subagent's conversation: its saved history, and its running response's
 * packets from the live stream, which the saved packets lag. `streamId` is
 * the agents list's live stream for the agent: a new one reloads the history,
 * which names the stream to follow; its end reloads the history too. The
 * history reloads when the stream ends, and a dropped stream resumes from its
 * last cursor. `runId` is the agent's latest run on the selected branch: the
 * history is keyed on it, so another branch's transcript replaces the old one.
 */
export function useSubagentTranscript(
  sessionId: string,
  agentId: string,
  streamId: number | null,
  runId: number | null
): SubagentTranscript {
  const url = SWR_KEYS.chatSubagentHistory(sessionId, agentId);
  const { data, error, isLoading, mutate } = useSWR<SubagentHistory, Error>(
    [url, runId],
    () => errorHandlingFetcher<SubagentHistory>(url),
    { onErrorRetry: skipRetryOnAuthError, revalidateOnFocus: false }
  );
  const stream = data?.stream ?? null;
  const followed = stream?.stream_id ?? null;
  const liveResponseId = stream?.response_ids[0] ?? null;

  // The agents list names another stream, or none once the agent ended
  useEffect(() => {
    if (streamId !== followed) void mutate();
  }, [streamId, followed, mutate]);

  const [live, setLive] = useState<{ streamId: number; packets: Packet[] }>({
    streamId: 0,
    packets: [],
  });
  useEffect(() => {
    if (followed === null) return;
    const controller = new AbortController();
    let pending: Packet[] = [];
    let frame: number | null = null;
    // Packets land once per frame, as the chat's own stream does
    const flush = () => {
      frame = null;
      const batch = pending;
      pending = [];
      setLive((current) =>
        current.streamId === followed
          ? { streamId: followed, packets: [...current.packets, ...batch] }
          : { streamId: followed, packets: batch }
      );
    };
    setLive({ streamId: followed, packets: [] });
    void (async () => {
      let cursor = 0;
      let stopped = false;
      // Until the stream sends its stop, or no longer serves this stream
      while (!stopped && !controller.signal.aborted) {
        // The stream sends a cursor after each batch of packets. A batch
        // lands with its cursor, so a drop before it cannot repeat packets
        let batch: Packet[] = [];
        try {
          for await (const item of followSubagentStream(
            sessionId,
            agentId,
            followed,
            cursor,
            controller.signal
          )) {
            if (!isPacket(item)) {
              cursor = item.next_cursor;
              if (batch.length > 0) {
                pending.push(...batch);
                if (batch.some((packet) => packet.obj.type === "stop"))
                  stopped = true;
                batch = [];
                if (frame === null) frame = requestAnimationFrame(flush);
              }
              continue;
            }
            const type = item.obj.type;
            if (type === "chat_heartbeat" || type === "replay_end") continue;
            batch.push(item);
          }
        } catch (failure) {
          if (controller.signal.aborted) return;
          if (failure instanceof FetchError && failure.status === 404) break;
          console.warn("The subagent's live stream dropped", failure);
        }
        if (!stopped)
          await new Promise((resolve) =>
            setTimeout(resolve, RECONNECT_DELAY_MS)
          );
      }
      if (controller.signal.aborted) return;
      if (frame !== null) cancelAnimationFrame(frame);
      flush();
      // The saved response replaces the stream
      void mutate();
    })();
    return () => {
      controller.abort();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [sessionId, agentId, followed, mutate]);

  const messages = useMemo(() => {
    if (!data) return [];
    // Each message the parent sends starts a reply that no earlier reply
    // links to as its latest child, so the conversation reads in order
    const chain = [
      ...processRawChatHistory(data.messages, data.packets).values(),
    ].sort((a, b) => (a.messageId ?? 0) - (b.messageId ?? 0));
    const streamed = live.streamId === followed ? live.packets : [];
    if (liveResponseId === null || streamed.length === 0) return chain;
    return chain.map((message) =>
      message.messageId === liveResponseId
        ? { ...message, packets: streamed }
        : message
    );
  }, [data, live, followed, liveResponseId]);

  return {
    messages,
    loading: isLoading,
    failed: error !== undefined,
  };
}
