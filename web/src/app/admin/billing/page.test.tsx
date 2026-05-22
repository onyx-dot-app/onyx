/**
 * Tests for BillingPage handleBillingReturn retry logic.
 *
 * The retry logic retries claimLicense up to 3 times with 2s backoff
 * when returning from a Stripe checkout session. This prevents the user
 * from getting stranded when the Stripe webhook fires concurrently with
 * the browser redirect and the license isn't ready yet.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
  mock,
  test,
} from "bun:test";
import React from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { act } from "@testing-library/react";

// Bun's fake-timer API lacks runAllTimersAsync/advanceTimersByTimeAsync.
// The retry chain is: claimLicense (rejected promise) -> .catch -> setTimeout
// -> resolve -> next loop iteration. Each step is a microtask, so we must
// flush microtasks BEFORE checking timer count: the first setTimeout isn't
// scheduled until the first rejected promise's catch handler runs.
async function flushMicrotasks(): Promise<void> {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

async function runAllTimersAsync(): Promise<void> {
  for (let i = 0; i < 30; i++) {
    await flushMicrotasks();
    if (jest.getTimerCount() === 0) return;
    jest.runAllTimers();
  }
}

async function advanceTimersByTimeAsync(ms: number): Promise<void> {
  await flushMicrotasks();
  jest.advanceTimersByTime(ms);
  await flushMicrotasks();
}

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

mock.module("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => mockSearchParams,
}));

mock.module("@/layouts/settings-layouts", () => ({
  Root: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="settings-root">{children}</div>
  ),
  Header: () => <div data-testid="settings-header" />,
  Body: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="settings-body">{children}</div>
  ),
}));

mock.module("@/layouts/general-layouts", () => ({
  Section: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

mock.module("@opal/icons", () => ({
  SvgArrowUpCircle: () => <svg />,
  SvgWallet: () => <svg />,
}));

mock.module("./PlansView", () => ({
  __esModule: true,
  default: () => <div data-testid="plans-view" />,
}));
mock.module("./CheckoutView", () => ({
  __esModule: true,
  default: () => <div data-testid="checkout-view" />,
}));
mock.module("./BillingDetailsView", () => ({
  __esModule: true,
  default: () => <div data-testid="billing-details-view" />,
}));
mock.module("./LicenseActivationCard", () => ({
  __esModule: true,
  default: () => <div data-testid="license-activation-card" />,
}));

// jest.requireActual is replaced with a top-level dynamic import.
const actualOpalComponents = await import("@opal/components");
mock.module("@opal/components", () => {
  return {
    ...actualOpalComponents,
    MessageCard: ({
      title,
      description,
      onClose,
    }: {
      title: string;
      description?: string;
      onClose?: () => void;
    }) => (
      <div data-testid="activating-banner">
        <span data-testid="activating-banner-text">{title}</span>
        {description && (
          <span data-testid="activating-banner-description">{description}</span>
        )}
        {onClose && (
          <button data-testid="activating-banner-close" onClick={onClose}>
            Close
          </button>
        )}
      </div>
    ),
  };
});

mock.module("@/lib/billing", () => ({
  useBillingInformation: jest.fn(),
  useLicense: jest.fn(),
  hasActiveSubscription: jest.fn().mockReturnValue(false),
  claimLicense: (...args: unknown[]) => mockClaimLicense(...args),
}));

mock.module("@/lib/constants", () => ({
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
    // Clear any activating state from prior tests
    sessionStorage.clear();
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
      await runAllTimersAsync();
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
      await runAllTimersAsync();
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
      await runAllTimersAsync();
    });

    await waitFor(() => {
      expect(mockClaimLicense).toHaveBeenCalledTimes(3);
    });
    // User stays on plans view with the activating banner
    await waitFor(() => {
      expect(screen.getByTestId("plans-view")).toBeInTheDocument();
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
      await runAllTimersAsync();
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
      await runAllTimersAsync();
    });

    expect(mockClaimLicense).not.toHaveBeenCalled();
  });

  test("shows activating banner and sets sessionStorage on 3x retry failure", async () => {
    mockSearchParams.get.mockImplementation((key: string) =>
      key === "session_id" ? "cs_all_fail" : null
    );
    mockClaimLicense.mockRejectedValue(new Error("Webhook not processed yet"));

    const consoleSpy = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});

    render(<BillingPage />);

    await act(async () => {
      await runAllTimersAsync();
    });

    await waitFor(() => {
      expect(screen.getByTestId("activating-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("activating-banner-text")).toHaveTextContent(
      "Your license is still activating"
    );
    expect(
      sessionStorage.getItem("billing_license_activating_until")
    ).not.toBeNull();

    consoleSpy.mockRestore();
  });

  test("banner not rendered when no activating state", async () => {
    mockSearchParams.get.mockReturnValue(null);

    render(<BillingPage />);

    await act(async () => {
      await runAllTimersAsync();
    });

    expect(screen.queryByTestId("activating-banner")).not.toBeInTheDocument();
  });

  test("banner shown on mount when sessionStorage key is set and not expired", async () => {
    sessionStorage.setItem(
      "billing_license_activating_until",
      String(Date.now() + 120_000)
    );
    mockSearchParams.get.mockReturnValue(null);

    render(<BillingPage />);

    // Flush React effects — banner is visible from lazy state init, no timer advancement needed
    await act(async () => {});

    expect(screen.getByTestId("activating-banner")).toBeInTheDocument();
  });

  test("banner not shown on mount when sessionStorage key is expired", async () => {
    sessionStorage.setItem(
      "billing_license_activating_until",
      String(Date.now() - 1000)
    );
    mockSearchParams.get.mockReturnValue(null);

    render(<BillingPage />);

    await act(async () => {
      await runAllTimersAsync();
    });

    expect(screen.queryByTestId("activating-banner")).not.toBeInTheDocument();
    expect(
      sessionStorage.getItem("billing_license_activating_until")
    ).toBeNull();
  });

  test("poll calls claimLicense after 15s and clears banner on success", async () => {
    sessionStorage.setItem(
      "billing_license_activating_until",
      String(Date.now() + 120_000)
    );
    mockSearchParams.get.mockReturnValue(null);
    // Poll attempt succeeds
    mockClaimLicense.mockResolvedValueOnce({ success: true });

    render(<BillingPage />);

    // Flush effects — banner visible from lazy state init
    await act(async () => {});
    expect(screen.getByTestId("activating-banner")).toBeInTheDocument();

    // Advance past one poll interval (15s)
    await act(async () => {
      await advanceTimersByTimeAsync(15_000);
    });

    expect(mockClaimLicense).toHaveBeenCalledWith(undefined);
    expect(screen.queryByTestId("activating-banner")).not.toBeInTheDocument();
    expect(
      sessionStorage.getItem("billing_license_activating_until")
    ).toBeNull();
    expect(mockRefreshBilling).toHaveBeenCalled();
    expect(mockRefreshLicense).toHaveBeenCalled();
    expect(mockRouter.refresh).toHaveBeenCalled();
  });

  test("close button removes banner and clears sessionStorage", async () => {
    sessionStorage.setItem(
      "billing_license_activating_until",
      String(Date.now() + 120_000)
    );
    mockSearchParams.get.mockReturnValue(null);

    render(<BillingPage />);

    // Flush effects — banner visible from lazy state init
    await act(async () => {});
    expect(screen.getByTestId("activating-banner")).toBeInTheDocument();

    const closeButton = screen.getByTestId("activating-banner-close");
    await act(async () => {
      closeButton.click();
    });

    expect(screen.queryByTestId("activating-banner")).not.toBeInTheDocument();
    expect(
      sessionStorage.getItem("billing_license_activating_until")
    ).toBeNull();
  });
});
