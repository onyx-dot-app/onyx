import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { deferred } from "@tests/setup/test-utils";
import {
  CraftStreamingProvider,
  useCraftStreaming,
} from "@/providers/CraftStreamingProvider";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  createTurn,
  fetchActiveTurn,
  fetchMessages,
  fetchOutputInventory,
  fetchTurnEventStream,
  processSSEStream,
} from "@/app/craft/services/apiServices";
import type { UserResolution } from "@/providers/UserProvider";

let mockUserId: string | null = "user-one";
let mockUserResolution: UserResolution = "resolved";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockUserId ? { id: mockUserId } : null,
    userResolution: mockUserResolution,
  }),
}));
jest.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));
jest.mock("@/app/craft/services/apiServices", () => ({
  RateLimitedError: class RateLimitedError extends Error {},
  createTurn: jest.fn(),
  fetchActiveTurn: jest.fn(),
  fetchMessages: jest.fn(),
  fetchOutputInventory: jest.fn(),
  fetchTurnEventStream: jest.fn(),
  processSSEStream: jest.fn(),
}));

const sessionId = "background-session";

function CraftPage() {
  const { streamMessage } = useCraftStreaming();
  return (
    <button onClick={() => void streamMessage(sessionId, "first prompt")}>
      Start
    </button>
  );
}

describe("CraftStreamingProvider", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUserId = "user-one";
    mockUserResolution = "resolved";
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
      outputInventory: {},
    });
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    jest.mocked(fetchMessages).mockResolvedValue([]);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [],
      complete: true,
    });
    // SAFETY: processSSEStream is mocked and does not read this response.
    jest.mocked(fetchTurnEventStream).mockResolvedValue({} as Response);
    jest.mocked(createTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "second-turn",
      status: "QUEUED",
      turn_index: 1,
    });
  });

  afterEach(() => {
    useBuildSessionStore.getState().cleanupOldSessions(0);
  });

  it("starts the queued prompt once after the Craft page unmounts", async () => {
    const firstStream = deferred<void>();
    const secondStream = deferred<void>();
    let completeFirst: (() => void) | undefined;
    jest.mocked(createTurn).mockResolvedValueOnce({
      session_id: sessionId,
      turn_id: "first-turn",
      status: "QUEUED",
      turn_index: 0,
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        completeFirst = () => {
          onPacket({ type: "prompt_response" });
          firstStream.resolve();
        };
        await firstStream.promise;
      })
      .mockImplementationOnce(async () => {
        await secondStream.promise;
        throw new DOMException("Closed", "AbortError");
      });
    const { rerender } = render(
      <CraftStreamingProvider>
        <CraftPage />
      </CraftStreamingProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(completeFirst).toBeDefined());
    act(() => {
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "queued prompt", []);
    });
    rerender(
      <CraftStreamingProvider>
        <div>Another page</div>
      </CraftStreamingProvider>
    );
    expect(
      screen.queryByRole("button", { name: "Start" })
    ).not.toBeInTheDocument();
    await act(async () => completeFirst?.());
    await waitFor(() => expect(createTurn).toHaveBeenCalledTimes(2));
    expect(jest.mocked(createTurn).mock.calls[1]?.[1]).toBe("queued prompt");
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toEqual([]);
    await act(async () => {
      useBuildSessionStore.getState().abortSession(sessionId);
      secondStream.resolve();
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
  });

  it("keeps queues during auth loading but clears them on confirmed logout", () => {
    const { rerender } = render(
      <CraftStreamingProvider>
        <div />
      </CraftStreamingProvider>
    );
    act(() => {
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "queued prompt", []);
    });
    mockUserId = null;
    mockUserResolution = "loading";
    rerender(
      <CraftStreamingProvider>
        <div />
      </CraftStreamingProvider>
    );
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toHaveLength(1);
    mockUserResolution = "resolved";
    rerender(
      <CraftStreamingProvider>
        <div />
      </CraftStreamingProvider>
    );
    expect(useBuildSessionStore.getState().sessions.size).toBe(0);
    expect(createTurn).not.toHaveBeenCalled();
  });

  it("clears the old queue before a different account can claim it", () => {
    const { rerender } = render(
      <CraftStreamingProvider>
        <div />
      </CraftStreamingProvider>
    );
    act(() => {
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "old account prompt", []);
    });
    mockUserId = "user-two";
    rerender(
      <CraftStreamingProvider>
        <div />
      </CraftStreamingProvider>
    );
    expect(useBuildSessionStore.getState().sessions.size).toBe(0);
    expect(createTurn).not.toHaveBeenCalled();
  });
});
