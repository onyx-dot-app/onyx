import { act, render, screen } from "@tests/setup/test-utils";
import { QueryControllerProvider } from "@/ee/providers/QueryControllerProvider";
import {
  useQueryController,
  type QueryControllerValue,
} from "@/providers/QueryControllerProvider";
import type { SearchFullResponse } from "@/lib/search/types";
import { classifyQuery, searchDocuments } from "@/ee/lib/search/svc";

const mockAppPosition = { isNewSession: () => true };
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => mockAppPosition,
}));
jest.mock("@/lib/tiers/hooks", () => ({ useTierAtLeast: () => true }));
jest.mock("@/lib/settings/hooks", () => ({
  useIsSearchModeAvailable: () => true,
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { preferences: { default_app_mode: "SEARCH" } } }),
}));
jest.mock("@/ee/lib/search/svc", () => ({
  classifyQuery: jest.fn(),
  searchDocuments: jest.fn(async () => ({
    search_docs: [{ document_id: "doc" }],
    llm_selected_doc_ids: null,
    error: null,
  })),
}));

let controller: QueryControllerValue | null = null;

function Probe() {
  controller = useQueryController();
  return (
    <output aria-label="Query phase">
      {`${controller.state.phase}:${controller.searchResults.length}`}
    </output>
  );
}

test("a chat-only query in search mode leaves the search results for chat", async () => {
  render(
    <QueryControllerProvider>
      <Probe />
    </QueryControllerProvider>
  );
  const onChat = jest.fn();
  await act(() => controller!.submit("find the docs", onChat));
  expect(screen.getByLabelText("Query phase")).toHaveTextContent(
    "search-results:1"
  );

  await act(() =>
    controller!.submit("use @code-review", onChat, { chatOnly: true })
  );
  expect(screen.getByLabelText("Query phase")).toHaveTextContent("chat:0");
  expect(onChat).toHaveBeenCalledTimes(1);
  expect(onChat).toHaveBeenCalledWith("use @code-review");
});

test("a chat-only query drops a search that is still pending", async () => {
  let resolveSearch: (response: SearchFullResponse) => void = () => undefined;
  jest.mocked(searchDocuments).mockImplementationOnce(
    (_query, options) =>
      new Promise<SearchFullResponse>((resolve, reject) => {
        resolveSearch = resolve;
        options?.signal?.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        );
      })
  );
  render(
    <QueryControllerProvider>
      <Probe />
    </QueryControllerProvider>
  );
  const onChat = jest.fn();
  let pendingSearch: Promise<void> = Promise.resolve();
  act(() => {
    pendingSearch = controller!.submit("find the docs", onChat);
  });
  expect(screen.getByLabelText("Query phase")).toHaveTextContent("searching:0");

  await act(() =>
    controller!.submit("use @code-review", onChat, { chatOnly: true })
  );
  await act(async () => {
    resolveSearch({
      all_executed_queries: ["find the docs"],
      search_docs: [
        { document_id: "doc" } as SearchFullResponse["search_docs"][number],
      ],
      llm_selected_doc_ids: null,
      error: null,
    });
    await pendingSearch;
  });

  expect(screen.getByLabelText("Query phase")).toHaveTextContent("chat:0");
  expect(onChat).toHaveBeenCalledWith("use @code-review");
});

test("a new query drops the search that an earlier auto-mode query started", async () => {
  let resolveSearch: (response: SearchFullResponse) => void = () => undefined;
  jest.mocked(searchDocuments).mockImplementationOnce(
    (_query, options) =>
      new Promise<SearchFullResponse>((resolve, reject) => {
        resolveSearch = resolve;
        options?.signal?.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        );
      })
  );
  jest
    .mocked(classifyQuery)
    .mockResolvedValueOnce({ is_search_flow: true })
    .mockImplementationOnce(
      (_query, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
          );
        })
    );
  render(
    <QueryControllerProvider>
      <Probe />
    </QueryControllerProvider>
  );
  act(() => controller!.setAppMode("auto"));
  const onChat = jest.fn();
  let pendingSearch: Promise<void> = Promise.resolve();
  await act(async () => {
    pendingSearch = controller!.submit("find the docs", onChat);
  });
  expect(screen.getByLabelText("Query phase")).toHaveTextContent("searching:0");

  act(() => {
    void controller!.submit("find other docs", onChat);
  });
  await act(async () => {
    resolveSearch({
      all_executed_queries: ["find the docs"],
      search_docs: [
        { document_id: "doc" } as SearchFullResponse["search_docs"][number],
      ],
      llm_selected_doc_ids: null,
      error: null,
    });
    await pendingSearch;
  });

  expect(screen.getByLabelText("Query phase")).toHaveTextContent(
    "classifying:0"
  );
  expect(onChat).not.toHaveBeenCalled();
});
