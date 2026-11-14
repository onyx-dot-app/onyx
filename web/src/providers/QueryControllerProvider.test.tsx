import { act, render, screen } from "@tests/setup/test-utils";
import { QueryControllerProvider } from "@/ee/providers/QueryControllerProvider";
import {
  useQueryController,
  type QueryControllerValue,
} from "@/providers/QueryControllerProvider";

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
});
