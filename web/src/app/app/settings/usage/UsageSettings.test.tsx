import { render, screen } from "@testing-library/react";
import UsageSettings from "@/app/app/settings/usage/UsageSettings";
import { useUserUsage } from "@/app/app/settings/usage/lib";

jest.mock("@/app/app/settings/usage/lib", () => ({
  useUserUsage: jest.fn(),
}));

const mockUseUserUsage = useUserUsage as jest.MockedFunction<
  typeof useUserUsage
>;

describe("UsageSettings", () => {
  beforeEach(() => {
    mockUseUserUsage.mockReturnValue({
      data: {
        per_day_by_model: [],
        window_cost_cents: 0,
        budget_cents: null,
        budget_remaining_cents: null,
        budget_period_hours: null,
        selected_model_price: null,
        available_model_prices: [],
      },
      error: undefined,
      isLoading: false,
      isValidating: false,
      mutate: jest.fn(),
    } as unknown as ReturnType<typeof useUserUsage>);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("uses a wrapping shared date range picker header", () => {
    render(<UsageSettings />);

    const picker = screen.getByRole("group", { name: "Date range" });

    expect(picker).toBeInTheDocument();
    expect(picker.parentElement).toHaveClass("flex-wrap");
  });
});
