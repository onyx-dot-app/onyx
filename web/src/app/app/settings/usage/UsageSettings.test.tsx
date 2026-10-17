import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import UsageSettings from "@/app/app/settings/usage/UsageSettings";
import { useUserUsage } from "@/app/app/settings/usage/lib";
import { formatCalendarDay } from "@/lib/dateUtils";

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

    expect(
      screen.getByText(`Resets on ${formatCalendarDay("2026-09-01")}`)
    ).toBeInTheDocument();
  });

  it("shows the top three models before expanding the breakdown", async () => {
    const user = userEvent.setup();
    mockUseUserUsage.mockReturnValue({
      data: {
        per_day_by_model: [
          {
            day: "2026-08-08",
            model: "model-four",
            input_tokens: 400,
            output_tokens: 40,
            cache_read_tokens: 0,
            cost_cents: 4,
          },
          {
            day: "2026-08-07",
            model: "model-four",
            input_tokens: 50,
            output_tokens: 5,
            cache_read_tokens: 0,
            cost_cents: 3,
          },
          {
            day: "2026-08-10",
            model: "model-two",
            input_tokens: 200,
            output_tokens: 20,
            cache_read_tokens: 0,
            cost_cents: 8,
          },
          {
            day: "2026-08-11",
            model: "model-one",
            input_tokens: 100,
            output_tokens: 10,
            cache_read_tokens: 0,
            cost_cents: 10,
          },
          {
            day: "2026-08-09",
            model: "model-three",
            input_tokens: 300,
            output_tokens: 30,
            cache_read_tokens: 0,
            cost_cents: 6,
          },
        ],
        window_cost_cents: 28,
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

    render(<UsageSettings />);

    expect(screen.getByText("model-one")).toBeInTheDocument();
    expect(screen.getByText("model-two")).toBeInTheDocument();
    expect(screen.getByText("model-four")).toBeInTheDocument();
    expect(screen.getByTestId("usage-model-preview")).toHaveAttribute(
      "aria-hidden",
      "true"
    );
    expect(screen.getByText("Show 1 more")).toBeInTheDocument();
    // The settings screenshot spec hides these counts, so keep the hook stable.
    expect(screen.getAllByTestId("usage-model-tokens")[0]).toHaveTextContent(
      "100 in · 10 out"
    );
    expect(screen.getByTestId("usage-model-preview")).toHaveClass(
      "[mask-image:linear-gradient(to_bottom,black_5%,transparent_75%)]"
    );
    expect(screen.getByTestId("usage-models-expander")).not.toHaveClass(
      "bg-background-tint-00"
    );

    await user.click(
      screen.getByRole("button", { name: "Show 1 more models" })
    );

    expect(screen.getByText("model-three")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show fewer models" })
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByTestId("usage-model-preview")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show fewer models" }));

    expect(screen.getByTestId("usage-model-preview")).toHaveAttribute(
      "aria-hidden",
      "true"
    );
  });
});
