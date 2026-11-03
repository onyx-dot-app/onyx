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
  fetchKnownTurn,
  fetchMessages,
  fetchOutputInventory,
  fetchTurnEventStream,
  interruptMessageStream,
  processSSEStream,
} from "@/app/craft/services/apiServices";
import type { UserResolution } from "@/providers/UserProvider";

let mockUserId: string | null = "user-one";
let mockUserResolution: UserResolution = "resolved";
let mockPathname = "/craft/v1";
const mockMutate = jest.fn();
jest.mock("next/navigation", () => ({ usePathname: () => mockPathname }));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockUserId ? { id: mockUserId } : null,
    userResolution: mockUserResolution,
  }),
}));
jest.mock("swr", () => ({
  mutate: () => Promise.resolve(undefined),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));
jest.mock("@/app/craft/services/apiServices", () => ({
  RateLimitedError: class RateLimitedError extends Error {},
  createTurn: jest.fn(),
  fetchActiveTurn: jest.fn(),
  fetchKnownTurn: jest.fn(),
  fetchMessages: jest.fn(),
  fetchOutputInventory: jest.fn(),
  fetchTurnEventStream: jest.fn(),
  interruptMessageStream: jest.fn(),
  processSSEStream: jest.fn(),
}));

const sessionId = "background-session";

function CraftPage() {
  const { streamMessage, interruptStreaming } = useCraftStreaming();
  return (
    <>
      <button onClick={() => void streamMessage(sessionId, "first prompt")}>
        Start
      </button>
      <button onClick={() => void interruptStreaming(sessionId)}>Stop</button>
    </>
  );
}

describe("CraftStreamingProvider", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUserId = "user-one";
    mockUserResolution = "resolved";
    mockPathname = "/craft/v1";
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
    jest.mocked(fetchKnownTurn).mockImplementation(async (id, turnId) => ({
      session_id: id,
      turn_id: turnId,
      status: "SUCCEEDED",
      turn_index: 0,
    }));
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
    mockPathname = "/app";
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

  it.each([false, true])(
    "reloads a different account without claiming old work (logout: %s)",
    (logoutFirst) => {
      const navigationError = jest
        .spyOn(console, "error")
        .mockImplementation(() => {});
      try {
        const { rerender } = render(
          <CraftStreamingProvider>
            <div />
          </CraftStreamingProvider>
        );
        if (logoutFirst) {
          mockUserId = null;
          rerender(
            <CraftStreamingProvider>
              <div />
            </CraftStreamingProvider>
          );
          expect(navigationError).not.toHaveBeenCalled();
        }
        mockUserId = "user-two";
        rerender(
          <CraftStreamingProvider>
            <div />
          </CraftStreamingProvider>
        );
        expect(navigationError).toHaveBeenCalledWith(
          expect.objectContaining({
            message: expect.stringContaining("Not implemented: navigation"),
          })
        );
        expect(createTurn).not.toHaveBeenCalled();
      } finally {
        navigationError.mockRestore();
      }
    }
  );

  it("follows an adopted successor offpage before dispatching the queued prompt once", async () => {
    const first = deferred<void>();
    const successor = deferred<void>();
    const queued = deferred<void>();
    let completeFirst: (() => void) | undefined;
    let completeSuccessor: (() => void) | undefined;
    jest.mocked(createTurn).mockResolvedValueOnce({
      session_id: sessionId,
      turn_id: "first-turn",
      status: "QUEUED",
      turn_index: 0,
    });
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce({
      session_id: sessionId,
      turn_id: "external-turn",
      status: "RUNNING",
      turn_index: 1,
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        completeFirst = () => {
          onPacket({ type: "prompt_response" });
          first.resolve();
        };
        await first.promise;
      })
      .mockImplementationOnce(async (_response, onPacket) => {
        completeSuccessor = () => {
          onPacket({ type: "prompt_response" });
          successor.resolve();
        };
        await successor.promise;
      })
      .mockImplementationOnce(async () => {
        await queued.promise;
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
    mockPathname = "/app";
    rerender(
      <CraftStreamingProvider>
        <div>Another page</div>
      </CraftStreamingProvider>
    );
    await act(async () => completeFirst?.());
    await waitFor(() => expect(completeSuccessor).toBeDefined());
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(fetchTurnEventStream).toHaveBeenCalledTimes(2);
    expect(jest.mocked(fetchTurnEventStream).mock.calls[1]?.[1]).toBe(
      "external-turn"
    );
    await act(async () => completeSuccessor?.());
    await waitFor(() => expect(createTurn).toHaveBeenCalledTimes(2));
    expect(jest.mocked(createTurn).mock.calls[1]?.[1]).toBe("queued prompt");
    await act(async () => {
      useBuildSessionStore.getState().abortSession(sessionId);
      queued.resolve();
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
  });
  it.each(["acknowledged", "failed"] as const)(
    "serializes a preaccept Stop that %s before repeating it for the accepted turn",
    async (outcome) => {
      const accepted = deferred<Awaited<ReturnType<typeof createTurn>>>();
      const firstStop = deferred<boolean>();
      const acceptedStop = deferred<boolean>();
      const queuedStream = deferred<void>();
      jest.mocked(createTurn).mockReturnValueOnce(accepted.promise);
      jest
        .mocked(interruptMessageStream)
        .mockReturnValueOnce(firstStop.promise)
        .mockReturnValueOnce(acceptedStop.promise);
      jest.mocked(fetchKnownTurn).mockImplementation(async (id, turnId) => ({
        session_id: id,
        turn_id: turnId,
        status: turnId === "first-turn" ? "CANCELLED" : "SUCCEEDED",
        turn_index: 0,
      }));
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          onPacket({ type: "prompt_response" });
        })
        .mockImplementationOnce(async () => {
          await queuedStream.promise;
          throw new DOMException("Closed", "AbortError");
        });
      const store = useBuildSessionStore.getState();
      store.setCurrentSession(sessionId);
      const view = render(
        <CraftStreamingProvider>
          <CraftPage />
        </CraftStreamingProvider>
      );
      try {
        fireEvent.click(screen.getByRole("button", { name: "Start" }));
        act(() => {
          store.enqueueMessage(sessionId, "queued prompt", []);
        });
        fireEvent.click(screen.getByRole("button", { name: "Stop" }));
        await act(async () => {
          accepted.resolve({
            session_id: sessionId,
            turn_id: "first-turn",
            status: "QUEUED",
            turn_index: 0,
          });
        });
        expect(interruptMessageStream).toHaveBeenCalledTimes(1);
        expect(fetchTurnEventStream).not.toHaveBeenCalled();
        expect(createTurn).toHaveBeenCalledTimes(1);
        await act(async () => {
          if (outcome === "failed")
            firstStop.reject(new Error("First Stop failed"));
          else firstStop.resolve(true);
        });
        expect(interruptMessageStream).toHaveBeenCalledTimes(2);
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({ isInterrupting: true, wasInterrupted: true });
        expect(fetchTurnEventStream).not.toHaveBeenCalled();
        expect(createTurn).toHaveBeenCalledTimes(1);
        await act(async () => acceptedStop.resolve(true));
        await waitFor(() => expect(createTurn).toHaveBeenCalledTimes(2));
        expect(jest.mocked(createTurn).mock.calls[1]?.[1]).toBe(
          "queued prompt"
        );
        expect(interruptMessageStream).toHaveBeenCalledTimes(2);
      } finally {
        view.unmount();
        store.abortSession(sessionId);
        await act(async () => queuedStream.resolve());
      }
    }
  );

  it.each(["missing-response", "terminal-packet", "active-check"] as const)(
    "keeps the Stop barrier on %s and adopts an external successor after acknowledgement",
    async (ending) => {
      const firstResponse =
        deferred<Awaited<ReturnType<typeof fetchTurnEventStream>>>();
      const firstStream = deferred<void>();
      const activeCheck =
        deferred<Awaited<ReturnType<typeof fetchActiveTurn>>>();
      const stop = deferred<boolean>();
      const successorStream = deferred<void>();
      const queuedStream = deferred<void>();
      let endFirst: (() => void) | undefined;
      let endSuccessor: (() => void) | undefined;
      jest.mocked(createTurn).mockResolvedValueOnce({
        session_id: sessionId,
        turn_id: "first-turn",
        status: "QUEUED",
        turn_index: 0,
      });
      jest
        .mocked(fetchTurnEventStream)
        .mockReturnValueOnce(firstResponse.promise)
        .mockResolvedValueOnce(null);
      jest.mocked(interruptMessageStream).mockReturnValueOnce(stop.promise);
      if (ending === "active-check") {
        jest.mocked(fetchActiveTurn).mockReturnValueOnce(activeCheck.promise);
        jest.mocked(processSSEStream).mockImplementationOnce(async () => {});
      }
      if (ending === "terminal-packet")
        jest
          .mocked(processSSEStream)
          .mockImplementationOnce(async (_response, onPacket) => {
            endFirst = () => {
              onPacket({ type: "prompt_response" });
              firstStream.resolve();
            };
            await firstStream.promise;
          });
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          endSuccessor = () => {
            onPacket({ type: "prompt_response" });
            successorStream.resolve();
          };
          await successorStream.promise;
        })
        .mockImplementationOnce(async () => {
          await queuedStream.promise;
          throw new DOMException("Closed", "AbortError");
        });
      const store = useBuildSessionStore.getState();
      store.setCurrentSession(sessionId);
      const view = render(
        <CraftStreamingProvider>
          <CraftPage />
        </CraftStreamingProvider>
      );
      try {
        fireEvent.click(screen.getByRole("button", { name: "Start" }));
        await act(async () => {});
        if (ending !== "missing-response") {
          firstResponse.resolve(new Response());
          await act(async () => {});
        }
        if (ending === "active-check")
          expect(fetchActiveTurn).toHaveBeenCalledTimes(1);
        act(() => {
          store.enqueueMessage(sessionId, "queued prompt", []);
        });
        fireEvent.click(screen.getByRole("button", { name: "Stop" }));
        await act(async () => {
          if (ending === "terminal-packet") endFirst?.();
          else if (ending === "active-check") activeCheck.resolve(null);
          else firstResponse.resolve(null);
        });
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({
          isInterrupting: true,
          turnSettlement: null,
          activeTurnLocalOwner: false,
        });
        expect(createTurn).toHaveBeenCalledTimes(1);
        jest.mocked(fetchActiveTurn).mockResolvedValue({
          session_id: sessionId,
          turn_id: "external-turn",
          status: "RUNNING",
          turn_index: 1,
        });
        await act(async () => stop.resolve(true));
        await waitFor(() => expect(endSuccessor).toBeDefined());
        expect(jest.mocked(fetchTurnEventStream).mock.calls[2]?.[1]).toBe(
          "external-turn"
        );
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({
          isInterrupting: false,
          activeTurnId: "external-turn",
          status: "running",
        });
        expect(createTurn).toHaveBeenCalledTimes(1);
        jest.mocked(fetchActiveTurn).mockResolvedValue(null);
        await act(async () => endSuccessor?.());
        await waitFor(() => expect(createTurn).toHaveBeenCalledTimes(2));
        expect(jest.mocked(createTurn).mock.calls[1]?.[1]).toBe(
          "queued prompt"
        );
      } finally {
        view.unmount();
        store.abortSession(sessionId);
        await act(async () => queuedStream.resolve());
      }
    }
  );

  it.each(["local", "external"] as const)(
    "resumes %s live ownership after failed Stop and follows completion beyond thirty seconds",
    async (ownership) => {
      jest.useFakeTimers();
      const first = deferred<void>();
      const resumed = deferred<void>();
      const queued = deferred<void>();
      const stop = deferred<boolean>();
      let completeResumed: (() => void) | undefined;
      jest.mocked(interruptMessageStream).mockReturnValueOnce(stop.promise);
      jest.mocked(fetchActiveTurn).mockResolvedValue({
        session_id: sessionId,
        turn_id: "second-turn",
        status: "RUNNING",
        turn_index: 1,
      });
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async () => {
          await first.promise;
        })
        .mockImplementationOnce(async (_response, onPacket) => {
          completeResumed = () => {
            onPacket({ type: "prompt_response" });
            resumed.resolve();
          };
          await resumed.promise;
        })
        .mockImplementationOnce(async () => {
          await queued.promise;
          throw new DOMException("Closed", "AbortError");
        });
      const store = useBuildSessionStore.getState();
      store.setCurrentSession(sessionId);
      if (ownership === "external")
        store.updateSessionData(sessionId, {
          status: "running",
          activeTurnId: "second-turn",
          activeTurnLocalOwner: false,
        });
      const view = render(
        <CraftStreamingProvider>
          <CraftPage />
        </CraftStreamingProvider>
      );
      try {
        if (ownership === "local")
          fireEvent.click(screen.getByRole("button", { name: "Start" }));
        await act(async () => {});
        expect(fetchTurnEventStream).toHaveBeenCalledTimes(1);
        act(() => {
          store.enqueueMessage(sessionId, "queued prompt", []);
          fireEvent.click(screen.getByRole("button", { name: "Stop" }));
        });
        await act(async () => first.resolve());
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({
          isInterrupting: true,
          activeTurnId: "second-turn",
          activeTurnLocalOwner: false,
        });
        expect(fetchTurnEventStream).toHaveBeenCalledTimes(1);
        await act(async () => stop.reject(new Error("Stop request rejected")));
        expect(fetchTurnEventStream).toHaveBeenCalledTimes(2);
        expect(completeResumed).toBeDefined();
        await act(async () => {
          await jest.advanceTimersByTimeAsync(31000);
        });
        expect(fetchTurnEventStream).toHaveBeenCalledTimes(2);
        expect(createTurn).toHaveBeenCalledTimes(ownership === "local" ? 1 : 0);
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({
          status: "running",
          activeTurnId: "second-turn",
          activeTurnLocalOwner: false,
        });
        jest.mocked(fetchActiveTurn).mockResolvedValue(null);
        await act(async () => completeResumed?.());
        expect(createTurn).toHaveBeenCalledTimes(ownership === "local" ? 2 : 1);
        expect(fetchTurnEventStream).toHaveBeenCalledTimes(3);
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
            ?.activeTurnLocalOwner
        ).toBe(true);
        await act(async () => {
          store.abortSession(sessionId);
          queued.resolve();
        });
      } finally {
        view.unmount();
        jest.useRealTimers();
      }
    }
  );
});
