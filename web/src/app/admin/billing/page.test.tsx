/**
 * Tests for BillingPage handleBillingReturn retry logic.
 *
 * The retry logic retries claimLicense up to 3 times with 2s backoff
 * when returning from a Stripe checkout session. This prevents the user
 * from getting stranded when the Stripe webhook fires concurrently with
 * the browser redirect and the license isn't ready yet.
 */
import React from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { act } from "@testing-library/react";

// ---- Stable mock objects (must be named with mock* prefix for jest hoisting) ----
// useRouter and useSearchParams must return the SAME reference each call, otherwise
// React's useEffect sees them as changed and re-runs the effect on every render.
const mockRouter = {
  replace: jest.fn() as jest.Mock,
  refresh: jest.fn() as jest.Mock,
};
const mockSearchParams = {
  get: jest.fn() as jest.Mock,
};
const mockClaimLicense = jest.fn() as jest.Mock;
const mockRefreshBilling = jest.fn() as jest.Mock;
const mockRefreshLicense = jest.fn() as jest.Mock;

// ---- Mocks ----

jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => mockSearchParams,
}));

jest.mock("@/layouts/settings-layouts", () => ({
  Root: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="settings-root">{children}</div>
  ),
  Header: () => <div data-testid="settings-header" />,
  Body: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="settings-body">{children}</div>
  ),
}));

jest.mock("@/layouts/general-layouts", () => ({
  Section: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

jest.mock("@opal/icons", () => ({
  SvgArrowUpCircle: () => <svg />,
  SvgWallet: () => <svg />,
}));

jest.mock("./PlansView", () => ({
  __esModule: true,
  default: () => <div data-testid="plans-view" />,
}));
jest.mock("./CheckoutView", () => ({
  __esModule: true,
  default: () => <div data-testid="checkout-view" />,
}));
jest.mock("./BillingDetailsView", () => ({
  __esModule: true,
  default: () => <div data-testid="billing-details-view" />,
}));
jest.mock("./LicenseActivationCard", () => ({
  __esModule: true,
  default: () => <div data-testid="license-activation-card" />,
}));

jest.mock("@/lib/billing", () => ({
  useBillingInformation: jest.fn(),
  useLicense: jest.fn(),
  hasActiveSubscription: jest.fn().mockReturnValue(false),
  claimLicense: (...args: unknown[]) => mockClaimLicense(...args),
}));

jest.mock("@/lib/constants", () => ({
  NEXT_PUBLIC_CLOUD_ENABLED: false,
}));

// ---- Import after mocks ----
import BillingPage from "./page";
import { useBillingInformation, useLicense } from "@/lib/billing";

// ---- Test helpers ----

function setupHooks() {
  (useBillingInformation as jest.Mock).mockReturnValue({
    data: null,
    isLoading: false,
    error: null,
    refresh: mockRefreshBilling,
  });
  (useLicense as jest.Mock).mockReturnValue({
    data: null,
    isLoading: false,
    refresh: mockRefreshLicense,
  });
}

// ---- Tests ----

describe("BillingPage — handleBillingReturn retry logic", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    setupHooks();
    // Default: no billing-return params
    mockSearchParams.get.mockReturnValue(null);
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  test("calls claimLicense once and refreshes on first-attempt success", async () => {
    mockSearchParams.get.mockImplementation((key: string) =>
      key === "session_id" ? "cs_test_123" : null
    );
    mockClaimLicense.mockResolvedValueOnce({ success: true });

    render(<BillingPage />);

    await act(async () => {
      await jest.runAllTimersAsync();
    });

    await waitFor(() => {
      expect(mockClaimLicense).toHaveBeenCalledTimes(1);
      expect(mockClaimLicense).toHaveBeenCalledWith("cs_test_123");
    });
    expect(mockRouter.refresh).toHaveBeenCalled();
    expect(mockRefreshBilling).toHaveBeenCalled();
    // URL cleaned up after checkout return
    expect(mockRouter.replace).toHaveBeenCalledWith("/admin/billing", {
      scroll: false,
    });
  });

  test("retries after first failure and succeeds on second attempt", async () => {
    mockSearchParams.get.mockImplementation((key: string) =>
      key === "session_id" ? "cs_retry_test" : null
    );
    mockClaimLicense
      .mockRejectedValueOnce(new Error("License not ready yet"))
      .mockResolvedValueOnce({ success: true });

    render(<BillingPage />);

    await act(async () => {
      await jest.runAllTimersAsync();
    });

    await waitFor(() => {
      expect(mockClaimLicense).toHaveBeenCalledTimes(2);
    });
    // On eventual success, router and billing should be refreshed
    expect(mockRouter.refresh).toHaveBeenCalled();
    expect(mockRefreshBilling).toHaveBeenCalled();
  });

  test("retries all 3 times then navigates to details even on total failure", async () => {
    mockSearchParams.get.mockImplementation((key: string) =>
      key === "session_id" ? "cs_all_fail" : null
    );
    // All 3 attempts fail
    mockClaimLicense.mockRejectedValue(new Error("Webhook not processed yet"));

    const consoleSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    render(<BillingPage />);

    await act(async () => {
      await jest.runAllTimersAsync();
    });

    await waitFor(() => {
      expect(mockClaimLicense).toHaveBeenCalledTimes(3);
    });
    // User just paid — they must not be stranded on plans view
    await waitFor(() => {
      expect(screen.getByTestId("billing-details-view")).toBeInTheDocument();
    });
    // refreshBilling still fires so billing state is up to date
    expect(mockRefreshBilling).toHaveBeenCalled();
    // Failure is logged
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed to sync license after billing return"),
      expect.any(Error)
    );

    consoleSpy.mockRestore();
  });

  test("calls claimLicense without session_id on portal_return", async () => {
    mockSearchParams.get.mockImplementation((key: string) =>
      key === "portal_return" ? "true" : null
    );
    mockClaimLicense.mockResolvedValueOnce({ success: true });

    render(<BillingPage />);

    await act(async () => {
      await jest.runAllTimersAsync();
    });

    await waitFor(() => {
      expect(mockClaimLicense).toHaveBeenCalledTimes(1);
      // No session_id for portal returns — called with undefined
      expect(mockClaimLicense).toHaveBeenCalledWith(undefined);
    });
    expect(mockRefreshBilling).toHaveBeenCalled();
  });

  test("does not call claimLicense when no billing-return params present", async () => {
    mockSearchParams.get.mockReturnValue(null);

    render(<BillingPage />);

    await act(async () => {
      await jest.runAllTimersAsync();
    });

    expect(mockClaimLicense).not.toHaveBeenCalled();
  });
});
