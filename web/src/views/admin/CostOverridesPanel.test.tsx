import type { ReactNode } from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CostOverridesPanel from "@/views/admin/CostOverridesPanel";
import type { CostOverride } from "@/lib/languageModels/costOverrides";

const mockMutate = jest.fn();
const mockRefreshCostOverrides = jest.fn();
const mockUpsertCostOverride = jest.fn();

const costOverrides: CostOverride[] = [
  {
    model: "shared-model",
    provider: "openai",
    input_cost_per_mtok: 1,
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

jest.mock("@/sections/model-selector/ModelSelector", () => ({
  __esModule: true,
  default: ({
    onChange,
    renderTrigger,
  }: {
    onChange: (option: {
      modelName: string;
      provider: string;
      modelConfigurationId: number;
    }) => void;
    renderTrigger: () => ReactNode;
  }) => (
    <>
      {renderTrigger()}
      <button
        onClick={() =>
          onChange({
            modelName: "shared-model",
            provider: "anthropic",
            modelConfigurationId: 1,
          })
        }
      >
        Choose Anthropic model
      </button>
    </>
  ),
}));

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

    expect(screen.getByText(/OpenAI · In \$1.00/)).toBeInTheDocument();
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
      screen.getByRole("button", { name: "Choose Anthropic model" })
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
});
