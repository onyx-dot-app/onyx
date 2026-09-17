import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { TokenRateLimitTable } from "@/app/admin/token-rate-limits/TokenRateLimitTables";
import type { TokenRateLimitDisplay } from "@/app/admin/token-rate-limits/types";

const mockDelete = jest.fn();
const mockMutate = jest.fn();
const mockToastError = jest.fn();
const mockUpdate = jest.fn();

jest.mock("@/app/admin/token-rate-limits/lib", () => ({
  deleteTokenRateLimit: (...args: unknown[]) => mockDelete(...args),
  updateTokenRateLimit: (...args: unknown[]) => mockUpdate(...args),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: {
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  mutate: (...args: unknown[]) => mockMutate(...args),
}));

function tokenRateLimit(
  periodHours: number,
  tokenBudget: number | null,
  costBudgetCents: number | null
): TokenRateLimitDisplay {
  return {
    token_id: 1,
    enabled: true,
    token_budget: tokenBudget,
    period_hours: periodHours,
    cost_budget_cents: costBudgetCents,
  };
}

test.each([
  [
    "token-only",
    tokenRateLimit(24, 1, null),
    "Up to 1,000 tokens",
    "Resets every day at midnight UTC",
  ],
  [
    "cost-only",
    tokenRateLimit(24, null, 100),
    "Up to $1.00",
    "Resets every day at midnight UTC",
  ],
  [
    "dual",
    tokenRateLimit(48, 1, 100),
    "Up to $1.00 or 1,000 tokens",
    "Resets every 2 days at midnight UTC",
  ],
])("%s limits render budget and cadence", (_name, limit, budget, cadence) => {
  render(
    <TokenRateLimitTable
      tokenRateLimits={[limit]}
      fetchUrl="/api/test-limits"
      isAdmin
    />
  );

  expect(screen.getByText(budget)).toBeInTheDocument();
  expect(screen.getByText(cadence)).toBeInTheDocument();
});

describe("token rate limit mutation failures", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("shows an update error instead of rejecting the click handler", async () => {
    const user = setupUser();
    mockUpdate.mockRejectedValue(new Error("Update failed"));
    render(
      <TokenRateLimitTable
        tokenRateLimits={[tokenRateLimit(24, 1, null)]}
        fetchUrl="/api/test-limits"
        isAdmin
      />
    );

    await user.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith("Update failed")
    );
    expect(mockMutate).not.toHaveBeenCalled();
  });

  test("shows a delete error instead of rejecting the click handler", async () => {
    const user = setupUser();
    mockDelete.mockRejectedValue(new Error("Delete failed"));
    render(
      <TokenRateLimitTable
        tokenRateLimits={[tokenRateLimit(24, 1, null)]}
        fetchUrl="/api/test-limits"
        isAdmin
      />
    );

    await user.click(screen.getByRole("button", { name: /^Delete Up to/ }));

    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith("Delete failed")
    );
    expect(mockMutate).not.toHaveBeenCalled();
  });
});
