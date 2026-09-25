import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CostOverridesPanel from "@/views/admin/CostOverridesPanel";
import type { CostOverride } from "@/lib/languageModels/types";

const mockMutate = jest.fn();
const mockRefreshCostOverrides = jest.fn();
const mockUpsertCostOverride = jest.fn();

const costOverrides: CostOverride[] = [
  {
    model: "shared-model",
    provider: "openai",
    input_cost_per_mtok: 0.001,
    output_cost_per_mtok: 2,
    cache_read_cost_per_mtok: null,
    updated_at: null,
  },
  {
    model: "shared-model",
    provider: "anthropic",
    input_cost_per_mtok: 3,
    output_cost_per_mtok: 4,
    cache_read_cost_per_mtok: null,
    updated_at: null,
  },
];

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("@/lib/languageModels/costOverrides", () => ({
  useCostOverrides: () => ({
    costOverrides,
    isLoading: false,
    error: undefined,
  }),
  deleteCostOverride: jest.fn(),
  refreshCostOverrides: (...args: unknown[]) =>
    mockRefreshCostOverrides(...args),
  upsertCostOverride: (...args: unknown[]) => mockUpsertCostOverride(...args),
}));

jest.mock("@/lib/languageModels/hooks", () => ({
  useAdminLanguageModels: () => ({
    llmProviders: [
      {
        id: 2,
        name: "Anthropic",
        provider: "anthropic",
        model_configurations: [
          {
            id: 1,
            name: "shared-model",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "shared-model",
          },
          {
            id: 3,
            name: "hidden-model",
            is_visible: false,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            effectiveDisplayName: "hidden-model",
          },
        ],
      },
    ],
  }),
}));

// A stand-in that exposes what the panel hands the picker: one button per
// offered model, and a clear button when the picker is nullable.
jest.mock("@/lib/languageModels/components", () => {
  const { Button } =
    jest.requireActual<typeof import("@opal/components")>("@opal/components");
  interface MockSelectorProps {
    providers: Array<{
      model_configurations: Array<{ id: number; effectiveDisplayName: string }>;
    }>;
    nullable?: boolean;
    onChange: (modelConfigurationId: number | null) => void;
  }
  function SimpleModelSelector({
    providers,
    nullable,
    onChange,
  }: MockSelectorProps) {
    return (
      <>
        {providers.flatMap((provider) =>
          provider.model_configurations.map((mc) => (
            <Button key={mc.id} onClick={() => onChange(mc.id)}>
              {`Choose ${mc.effectiveDisplayName}`}
            </Button>
          ))
        )}
        {nullable && (
          <Button onClick={() => onChange(null)}>Clear model</Button>
        )}
      </>
    );
  }
  return { SimpleModelSelector };
});

describe("CostOverridesPanel", () => {
  beforeEach(() => {
    mockRefreshCostOverrides.mockResolvedValue(undefined);
    mockUpsertCostOverride.mockResolvedValue(costOverrides[1]);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test("distinguishes the same model under different providers", () => {
    render(<CostOverridesPanel />);

    expect(screen.getByText(/OpenAI · In \$0.001/)).toBeInTheDocument();
    expect(screen.getByText(/Anthropic · In \$3.00/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Edit Anthropic override for shared-model",
      })
    ).toBeInTheDocument();
  });

  test("preserves the provider when editing an override", async () => {
    const user = setupUser();
    render(<CostOverridesPanel />);

    await user.click(
      screen.getByRole("button", {
        name: "Edit Anthropic override for shared-model",
      })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockUpsertCostOverride).toHaveBeenCalledWith({
        model: "shared-model",
        provider: "anthropic",
        input_cost_per_mtok: 3,
        output_cost_per_mtok: 4,
        cache_read_cost_per_mtok: null,
      });
    });
  });

  test("saves the selected provider when adding an override", async () => {
    const user = setupUser();
    render(<CostOverridesPanel />);

    await user.click(screen.getByRole("button", { name: "Add override" }));
    await user.click(
      screen.getByRole("button", { name: "Choose shared-model" })
    );

    await user.type(screen.getByPlaceholderText("3.00"), "3");
    await user.type(screen.getByPlaceholderText("15.00"), "4");
    const submitButton = screen.getAllByRole("button", {
      name: "Add override",
    })[1] as HTMLElement;
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockUpsertCostOverride).toHaveBeenCalledWith({
        model: "shared-model",
        provider: "anthropic",
        input_cost_per_mtok: 3,
        output_cost_per_mtok: 4,
        cache_read_cost_per_mtok: null,
      });
    });
  });

  test("offers hidden models and saves one", async () => {
    const user = setupUser();
    render(<CostOverridesPanel />);

    await user.click(screen.getByRole("button", { name: "Add override" }));
    await user.click(
      screen.getByRole("button", { name: "Choose hidden-model" })
    );
    await user.type(screen.getByPlaceholderText("3.00"), "1");
    await user.type(screen.getByPlaceholderText("15.00"), "2");
    const submitButton = screen.getAllByRole("button", {
      name: "Add override",
    })[1] as HTMLElement;
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockUpsertCostOverride).toHaveBeenCalledWith({
        model: "hidden-model",
        provider: "anthropic",
        input_cost_per_mtok: 1,
        output_cost_per_mtok: 2,
        cache_read_cost_per_mtok: null,
      });
    });
  });

  test("clearing the picked model blocks the save", async () => {
    const user = setupUser();
    render(<CostOverridesPanel />);

    await user.click(screen.getByRole("button", { name: "Add override" }));
    await user.click(
      screen.getByRole("button", { name: "Choose shared-model" })
    );
    await user.type(screen.getByPlaceholderText("3.00"), "3");
    await user.type(screen.getByPlaceholderText("15.00"), "4");
    const submitButton = screen.getAllByRole("button", {
      name: "Add override",
    })[1] as HTMLElement;
    expect(submitButton).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Clear model" }));

    expect(submitButton).toBeDisabled();
    expect(mockUpsertCostOverride).not.toHaveBeenCalled();
  });
});
