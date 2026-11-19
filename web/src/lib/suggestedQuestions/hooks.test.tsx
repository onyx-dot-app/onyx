import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { useSuggestedQuestions } from "@/lib/suggestedQuestions/hooks";

let mockIsPlayground = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ is_playground: mockIsPlayground }),
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

function mockFetch() {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async () =>
        new Response(JSON.stringify({ questions: [], state: "preparing" }))
    );
}

function requested(fetchMock: ReturnType<typeof mockFetch>): URL[] {
  return fetchMock.mock.calls.map(
    ([input]) => new URL(String(input), "http://localhost")
  );
}

beforeEach(() => {
  mockIsPlayground = true;
});

afterEach(() => jest.restoreAllMocks());

test("off the Playground nothing is requested", () => {
  mockIsPlayground = false;
  const fetchMock = mockFetch();

  renderHook(() => useSuggestedQuestions(0), { wrapper });

  expect(fetchMock).not.toHaveBeenCalled();
});

test("the first fetch is a chat open; later ones only read", async () => {
  const fetchMock = mockFetch();
  const { result } = renderHook(() => useSuggestedQuestions(0), { wrapper });
  await waitFor(() => expect(result.current.suggestions).toBeDefined());

  await act(async () => {
    await result.current.mutate();
  });

  const [open, poll] = requested(fetchMock);
  expect(open?.searchParams.get("poll")).toBe("false");
  expect(poll?.searchParams.get("poll")).toBe("true");
  // One seed per page load, so the pick does not change between fetches.
  expect(poll?.searchParams.get("seed")).toBe(open?.searchParams.get("seed"));
});

test("switching agents is a new chat open", async () => {
  const fetchMock = mockFetch();
  const { result, rerender } = renderHook(
    ({ agentId }: { agentId: number }) => useSuggestedQuestions(agentId),
    { wrapper, initialProps: { agentId: 0 } }
  );
  await waitFor(() => expect(result.current.suggestions).toBeDefined());

  rerender({ agentId: 7 });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  expect(
    requested(fetchMock).map((url) => [
      url.searchParams.get("agent_id"),
      url.searchParams.get("poll"),
    ])
  ).toEqual([
    ["0", "false"],
    ["7", "false"],
  ]);
});
