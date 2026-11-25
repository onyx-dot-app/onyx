/**
 * The run status of each chat that this tab holds, for the sidebar rows:
 * what a chat does now, and how a run ended while the user was elsewhere.
 */
import { create } from "zustand";
import { PacketType, StopReason } from "@/app/app/services/streamingModels";
import type { ChatState } from "@/app/app/types";
import {
  getLatestMessageChain,
  type MessageTreeState,
} from "@/app/app/services/messageTree";
import type { SessionError } from "@/app/app/stores/useChatSessionStore";
import type { ApprovalStatus } from "@/lib/approvals/types";
import {
  readWaitingToolRequests,
  type ToolQuestionStatus,
} from "@/lib/chat/toolApprovals";

export type ChatRunStatus = "working" | "approval" | "question" | EndedRun;

/** How a run ended, kept until the user opens the chat. */
export type EndedRun = "failed" | "done";

interface RunSession {
  chatState: ChatState;
  messageTree: MessageTreeState;
  uncaughtError: SessionError | null;
}

const WORKING_STATES: ReadonlySet<ChatState> = new Set<ChatState>([
  "loading",
  "streaming",
  "cancelling",
]);

export function isWorking(session: RunSession): boolean {
  return WORKING_STATES.has(session.chatState);
}

/**
 * What the chat waits for now: its run, or the user's decision on an
 * approval or a question. Requests that this client already decided do not
 * wait.
 */
export function liveRunStatus(
  session: RunSession,
  localStatuses: ReadonlyMap<string, ApprovalStatus> = new Map(),
  localAnswers: ReadonlyMap<string, ToolQuestionStatus> = new Map()
): "working" | "approval" | "question" | null {
  if (isWorking(session)) return "working";
  let question = false;
  for (const item of readWaitingToolRequests(session.messageTree)) {
    if (item.kind === "approval") {
      if (!localStatuses.has(item.request.approval_id)) return "approval";
    } else if (!localAnswers.has(item.request.question_request_id)) {
      question = true;
    }
  }
  return question ? "question" : null;
}

/** How a run that just stopped working ended. */
export function endedRunStatus(
  session: RunSession
): "approval" | "question" | EndedRun | null {
  const live = liveRunStatus(session);
  if (live === "approval" || live === "question") return live;
  const lastMessage = getLatestMessageChain(session.messageTree).at(-1);
  const finished = lastMessage?.packets?.findLast(
    (packet) => packet.obj.type === PacketType.STOP
  )?.obj;
  const failed =
    session.chatState === "unconfirmed" ||
    (session.uncaughtError != null &&
      session.uncaughtError.affectsRunStatus !== false) ||
    lastMessage?.type === "error" ||
    (finished?.type === PacketType.STOP &&
      finished.stop_reason === StopReason.TIMED_OUT);
  if (failed) return "failed";
  if (
    finished?.type === PacketType.STOP &&
    finished.stop_reason === StopReason.USER_CANCELLED
  )
    return null;
  return "done";
}

export const UNSEEN_RUNS_STORAGE_KEY = "onyx:unseen-runs:v1";
// The newest records kept; older ones (e.g. of deleted chats) are dropped.
const MAX_UNSEEN_RUNS = 50;
const ENDED_RUNS: ReadonlySet<string> = new Set<EndedRun>(["failed", "done"]);

function isEndedRun(value: unknown): value is EndedRun {
  return typeof value === "string" && ENDED_RUNS.has(value);
}

/** The records this browser saved, so a reload keeps them. */
function readUnseenRuns(): Map<string, EndedRun> {
  try {
    const parsed: unknown = JSON.parse(
      window.sessionStorage.getItem(UNSEEN_RUNS_STORAGE_KEY) ?? "[]"
    );
    if (!Array.isArray(parsed)) return new Map();
    const unseen = new Map<string, EndedRun>();
    for (const entry of parsed) {
      if (
        Array.isArray(entry) &&
        typeof entry[0] === "string" &&
        isEndedRun(entry[1])
      )
        unseen.set(entry[0], entry[1]);
    }
    return unseen;
  } catch {
    return new Map();
  }
}

function saveUnseenRuns(unseen: ReadonlyMap<string, EndedRun>): void {
  try {
    window.sessionStorage.setItem(
      UNSEEN_RUNS_STORAGE_KEY,
      JSON.stringify([...unseen].slice(-MAX_UNSEEN_RUNS))
    );
  } catch {
    // Blocked storage keeps the records for this page only.
  }
}

interface UnseenRunsState {
  unseen: ReadonlyMap<string, EndedRun>;
  markUnseen: (sessionId: string, ended: EndedRun) => void;
  markSeen: (sessionId: string) => void;
  clearAll: () => void;
}

/**
 * Runs that ended while their chat was off-screen. The browser keeps these
 * records across reloads until the user opens the chat.
 */
export const useUnseenRuns = create<UnseenRunsState>()((set) => ({
  unseen: typeof window === "undefined" ? new Map() : readUnseenRuns(),
  markUnseen: (sessionId, stopped) =>
    set((state) => {
      // A new record goes last, so the cap drops the oldest first.
      const unseen = new Map(state.unseen);
      unseen.delete(sessionId);
      unseen.set(sessionId, stopped);
      saveUnseenRuns(unseen);
      return { unseen };
    }),
  clearAll: () => {
    try {
      window.sessionStorage.removeItem(UNSEEN_RUNS_STORAGE_KEY);
    } catch {
      // Disabled storage does not affect the in-memory records.
    }
    set({ unseen: new Map() });
  },
  markSeen: (sessionId) =>
    set((state) => {
      if (!state.unseen.has(sessionId)) return {};
      const unseen = new Map(state.unseen);
      unseen.delete(sessionId);
      saveUnseenRuns(unseen);
      return { unseen };
    }),
}));
