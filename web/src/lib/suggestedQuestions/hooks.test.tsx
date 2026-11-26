import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import {
  nextPollDelay,
  useSuggestedQuestions,
} from "@/lib/suggestedQuestions/hooks";
import type { PersonSuggestions } from "@/lib/suggestedQuestions/types";

let mockIsPlayground = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ is_playground: mockIsPlayground }),
}));

// The hook remembers each agent's chat open for the whole page load, so each
// test uses its own agent id.
let nextAgentId = 100;
function newAgentId(): number {
  nextAgentId += 1;
  return nextAgentId;
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
        isVisible: () => true,
        isOnline: () => true,
      }}
    >
      {children}
    </SWRConfig>
  );
}

function body(state: PersonSuggestions["state"]): Response {
  return new Response(JSON.stringify({ questions: [], state }));
}

function urls(fetchMock: jest.SpyInstance): URL[] {
  return fetchMock.mock.calls.map(
    ([input]) => new URL(String(input), "http://localhost")
  );
}

function polls(fetchMock: jest.SpyInstance): (string | null)[] {
  return urls(fetchMock).map((url) => url.searchParams.get("poll"));
}

beforeEach(() => {
  mockIsPlayground = true;
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

test("off the Playground nothing is requested", () => {
  mockIsPlayground = false;
  const fetchMock = jest.spyOn(global, "fetch");

  renderHook(() => useSuggestedQuestions(newAgentId()), { wrapper });

  expect(fetchMock).not.toHaveBeenCalled();
});

test("the first fetch is a chat open; later ones only read", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => body("ready"));
  const agentId = newAgentId();
  const { result } = renderHook(() => useSuggestedQuestions(agentId), {
    wrapper,
  });
  await waitFor(() => expect(result.current.suggestions).toBeDefined());

  await act(async () => {
    await result.current.mutate();
  });

  expect(polls(fetchMock)).toEqual(["false", "true"]);
  // One seed per page load, so the pick does not change between fetches.
  const [open, poll] = urls(fetchMock);
  expect(poll?.searchParams.get("seed")).toBe(open?.searchParams.get("seed"));
});

test("a failed first fetch is retried as a chat open", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(new Response("down", { status: 500 }))
    .mockImplementation(async () => body("ready"));
  const agentId = newAgentId();
  const { result } = renderHook(() => useSuggestedQuestions(agentId), {
    wrapper,
  });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

  await act(async () => {
    await result.current.mutate();
  });

  expect(polls(fetchMock)).toEqual(["false", "false"]);
});

test("switching agents is a new chat open", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => body("ready"));
  const [first, second] = [newAgentId(), newAgentId()];
  const { result, rerender } = renderHook(
    ({ agentId }: { agentId: number }) => useSuggestedQuestions(agentId),
    { wrapper, initialProps: { agentId: first } }
  );
  await waitFor(() => expect(result.current.suggestions).toBeDefined());

  rerender({ agentId: second });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  expect(
    urls(fetchMock).map((url) => [
      url.searchParams.get("agent_id"),
      url.searchParams.get("poll"),
    ])
  ).toEqual([
    [String(first), "false"],
    [String(second), "false"],
  ]);
});

describe("checking again while questions are being prepared", () => {
  const opened = 1_000_000;
  const preparing: PersonSuggestions = { questions: [], state: "preparing" };
  const ready: PersonSuggestions = { questions: [], state: "ready" };

  test("checks every 5 seconds until just after the server's window", () => {
    expect(nextPollDelay(preparing, opened, opened)).toBe(5_000);
    // The server ends "preparing" at 120 s; one more check sees that.
    expect(nextPollDelay(preparing, opened, opened + 120_000)).toBe(5_000);
    expect(nextPollDelay(preparing, opened, opened + 125_000)).toBe(0);
  });

  test("stops once the questions are ready", () => {
    expect(nextPollDelay(ready, opened, opened + 5_000)).toBe(0);
  });

  test("does not check before the chat open reached the server", () => {
    expect(nextPollDelay(preparing, undefined, opened)).toBe(0);
    expect(nextPollDelay(undefined, opened, opened)).toBe(0);
  });
});
