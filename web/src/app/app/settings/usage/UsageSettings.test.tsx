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
        budget_reset_at: null,
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
    jest.useRealTimers();
    jest.clearAllMocks();
  });

  it("keeps the shared date range picker inline with the usage title", () => {
    render(<UsageSettings />);

    const picker = screen.getByRole("group", { name: "Date range" });

    expect(picker).toBeInTheDocument();
    expect(picker.parentElement).toHaveClass(
      "flex-wrap",
      "items-center",
      "justify-between"
    );
    expect(screen.getByText("Usage").parentElement).toBe(picker.parentElement);
  });

  it("shows the fixed budget reset date", () => {
    jest.useFakeTimers().setSystemTime(new Date("2026-08-12T12:00:00Z"));
    mockUseUserUsage.mockReturnValue({
      data: {
        per_day_by_model: [],
        window_cost_cents: 897.2,
        budget_cents: 1500,
        budget_remaining_cents: 602.8,
        budget_period_hours: 720,
        budget_reset_at: "2026-09-01T00:00:00Z",
        selected_model_price: null,
        available_model_prices: [],
      },
      error: undefined,
      isLoading: false,
      isValidating: false,
      mutate: jest.fn(),
    } as unknown as ReturnType<typeof useUserUsage>);

    render(<UsageSettings />);

    expect(screen.getByText("Resets on Sep 1")).toBeInTheDocument();
  });
});
