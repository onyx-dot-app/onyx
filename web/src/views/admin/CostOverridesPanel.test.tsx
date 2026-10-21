import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
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
// offered model, and a clear button when the picker is nullable. The Model
// row's <label> wraps these, so the first button takes the label's text as
// its accessible name; tests find the buttons by their own text instead.
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

// Rate rows in order: input (0), output (1), cache read (2).
function wholeAmountField(index: number): HTMLElement {
  const field = screen.getAllByRole("textbox", { name: "Whole amount" })[index];
  if (!field) throw new Error(`No whole-amount field at ${index}`);
  return field;
}

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

    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    for (const rate of ["In $0.001", "Out $2.00", "In $3.00", "Out $4.00"]) {
      expect(screen.getByText(rate)).toBeInTheDocument();
    }
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
    // Save stays disabled until a value changes.
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.clear(wholeAmountField(1));
    await user.type(wholeAmountField(1), "5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockUpsertCostOverride).toHaveBeenCalledWith({
        model: "shared-model",
        provider: "anthropic",
        input_cost_per_mtok: 3,
        output_cost_per_mtok: 5,
        cache_read_cost_per_mtok: null,
      });
    });
  });

  test("saves the selected provider when adding an override", async () => {
    const user = setupUser();
    render(<CostOverridesPanel />);

    await user.click(screen.getByRole("button", { name: "Add override" }));
    await user.click(screen.getByText("Choose shared-model"));

    await user.type(wholeAmountField(0), "3");
    await user.type(wholeAmountField(1), "4");
    const submitButton = within(screen.getByRole("dialog")).getByRole(
      "button",
      {
        name: "Add",
      }
    );
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
    await user.click(screen.getByText("Choose hidden-model"));
    await user.type(wholeAmountField(0), "1");
    await user.type(wholeAmountField(1), "2");
    const submitButton = within(screen.getByRole("dialog")).getByRole(
      "button",
      {
        name: "Add",
      }
    );
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
    await user.click(screen.getByText("Choose shared-model"));
    await user.type(wholeAmountField(0), "3");
    await user.type(wholeAmountField(1), "4");
    const submitButton = within(screen.getByRole("dialog")).getByRole(
      "button",
      {
        name: "Add",
      }
    );
    expect(submitButton).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Clear model" }));

    // Formik re-validates after setFieldValue asynchronously.
    await waitFor(() => expect(submitButton).toBeDisabled());
    expect(mockUpsertCostOverride).not.toHaveBeenCalled();
  });
});
