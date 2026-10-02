/** The provider edit modal, with Bifrost as the host, works from the listing's
 *  first page: the end of the list pages the next window in, a search asks the
 *  server, paged-in models are not edits, and the save sends only changes. */

import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import BifrostModal from "@/sections/modals/languageModels/BifrostModal";
import { SERVER_SEARCH_DEBOUNCE_MS } from "@/lib/languageModels/hooks";
import type {
  LLMProviderView,
  ModelConfiguration,
  ModelPaging,
} from "@/lib/languageModels/types";

const mockMutate = jest.fn();
jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    useSWRConfig: () => ({ mutate: mockMutate }),
    __esModule: true,
    default: () => ({ data: undefined, error: undefined, isLoading: false }),
  };
});

jest.mock("@opal/layouts/toast/store", () => {
  const toastFn = Object.assign(jest.fn(), {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
    _markLeaving: jest.fn(),
  });
  return {
    toast: toastFn,
    useToast: () => ({
      toast: toastFn,
      dismiss: toastFn.dismiss,
      clearAll: toastFn.clearAll,
    }),
  };
});

jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => false,
}));

const PROVIDER_ID = 7;

function model(
  id: number,
  name: string,
  isVisible: boolean
): ModelConfiguration {
  return {
    id,
    name,
    is_visible: isVisible,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    display_name: name,
    effectiveDisplayName: name,
  };
}

const FIRST_PAGE = [
  model(1, "alpha", true),
  model(2, "beta", true),
  model(3, "gamma", false),
  model(4, "delta", false),
];
const SECOND_PAGE = [model(5, "epsilon", false)];

function provider(
  models: ModelConfiguration[],
  nextOffset: number | null
): LLMProviderView {
  return {
    id: PROVIDER_ID,
    name: "Gateway",
    provider: "bifrost",
    api_key: null,
    api_base: "https://gateway.example",
    api_version: null,
    custom_config: null,
    is_public: true,
    is_auto_mode: false,
    groups: [],
    personas: [],
    deployment_name: null,
    model_configurations: models,
    next_model_configuration_offset: nextOffset,
  };
}

// What the admin listing currently holds for the provider. A test swaps it
// to stand in for a merged page.
let mockListing = provider(FIRST_PAGE, FIRST_PAGE.length);
const mockModelPaging: jest.Mocked<ModelPaging> = {
  hasMore: true,
  isLoading: false,
  loadMore: jest.fn(),
  search: jest.fn(),
  searchHasMore: false,
  loadMoreSearch: jest.fn(),
};
jest.mock("@/lib/languageModels/hooks", () => ({
  ...jest.requireActual("@/lib/languageModels/hooks"),
  useAdminLanguageModels: () => ({
    llmProviders: [mockListing],
    defaultText: null,
    defaultVision: null,
    defaultChatNaming: null,
    defaultCraft: null,
    isLoading: false,
    error: undefined,
    modelPaging: mockModelPaging,
    refetch: jest.fn(),
  }),
}));

let observerCallbacks: IntersectionObserverCallback[] = [];

function intersectSentinel() {
  act(() => {
    for (const callback of observerCallbacks) {
      callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver
      );
    }
  });
}

describe("BifrostModal with a paged provider", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    mockListing = provider(FIRST_PAGE, FIRST_PAGE.length);
    mockModelPaging.loadMore.mockResolvedValue(undefined);
    mockModelPaging.search.mockResolvedValue(true);
    observerCallbacks = [];
    global.IntersectionObserver = class {
      constructor(callback: IntersectionObserverCallback) {
        observerCallbacks.push(callback);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
      takeRecords() {
        return [];
      }
    } as unknown as typeof IntersectionObserver;
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("pages the provider in at the end of the list and saves only the edited model", async () => {
    const user = setupUser();
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({ id: PROVIDER_ID }),
    } as Response);

    const { rerender } = render(
      <BifrostModal existingLlmProvider={mockListing} onOpenChange={() => {}} />
    );
    expect(screen.getByText("alpha")).toBeInTheDocument();
    const updateButton = () => screen.getByRole("button", { name: /update/i });
    expect(updateButton()).toBeDisabled();

    // The fold hides the sentinel. Expanding the list reveals it.
    expect(screen.queryByTestId("model-list-sentinel")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /more models/i }));
    expect(screen.getByTestId("model-list-sentinel")).toBeInTheDocument();

    intersectSentinel();
    expect(mockModelPaging.loadMore).toHaveBeenCalledWith([PROVIDER_ID]);

    // Stands in for a merged page: the listing grows and the card hands the
    // modal every model shown so far.
    mockListing = provider([...FIRST_PAGE, ...SECOND_PAGE], null);
    rerender(
      <BifrostModal existingLlmProvider={mockListing} onOpenChange={() => {}} />
    );
    expect(await screen.findByText("epsilon")).toBeInTheDocument();
    expect(screen.queryByTestId("model-list-sentinel")).not.toBeInTheDocument();
    // A paged-in model is not an edit.
    expect(updateButton()).toBeDisabled();

    // The row, not its title: the title is an inline rename control.
    const epsilonRow = document
      .querySelector('[data-model-name="epsilon"]')!
      .querySelector<HTMLElement>('[role="button"]')!;
    await user.click(epsilonRow);
    // The button remounts when its disabled tooltip clears, so query it again.
    await waitFor(() => expect(updateButton()).toBeEnabled());
    await user.click(updateButton());

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/provider",
        expect.objectContaining({ method: "PUT" })
      );
    });
    const putCall = fetchSpy.mock.calls.find(
      (call) => call[0] === "/api/admin/llm/provider"
    );
    const body = JSON.parse(putCall![1].body as string);
    expect(body.keep_existing_models).toBe(true);
    expect(body.removed_model_names).toEqual([]);
    expect(body.model_configurations).toEqual([
      expect.objectContaining({ name: "epsilon", is_visible: true }),
    ]);
  });

  test("a search asks the server for the provider's unloaded matches", async () => {
    jest.useFakeTimers();
    try {
      const user = setupUser({ advanceTimers: jest.advanceTimersByTime });
      render(
        <BifrostModal
          existingLlmProvider={mockListing}
          onOpenChange={() => {}}
        />
      );

      await user.type(screen.getByPlaceholderText("Search models..."), "eps");
      // Loaded rows filter at once. The server call waits for the debounce.
      expect(screen.queryByText("alpha")).not.toBeInTheDocument();
      expect(mockModelPaging.search).not.toHaveBeenCalled();

      act(() => {
        jest.advanceTimersByTime(SERVER_SEARCH_DEBOUNCE_MS);
      });
      expect(mockModelPaging.search).toHaveBeenCalledWith("eps", [PROVIDER_ID]);
    } finally {
      jest.useRealTimers();
    }
  });
});
