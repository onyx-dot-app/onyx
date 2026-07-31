import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { formatPeriod } from "@/app/admin/token-rate-limits/TokenRateLimitTables";
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
  ["token-only", tokenRateLimit(24, 1, null), "1 UTC day"],
  ["cost-only", tokenRateLimit(24, null, 100), "1 UTC day"],
  ["dual", tokenRateLimit(48, 1, 100), "2 UTC days"],
])("%s limits display UTC-day windows", (_name, limit, expected) => {
  expect(formatPeriod(limit)).toBe(expected);
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

    await user.click(screen.getByRole("checkbox"));

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

    await user.click(screen.getByRole("button"));

    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith("Delete failed")
    );
    expect(mockMutate).not.toHaveBeenCalled();
  });
});
