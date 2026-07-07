import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import HealthBanner from "@/sections/banners/HealthBanner";

const mockUseSWR = jest.fn();
const mockUseCurrentUser = jest.fn();
const mockUseTokenExpiry = jest.fn();
const mockUseCustomTokenRefresh = jest.fn();
const mockUseSessionWatcher = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/lib/users/hooks", () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}));

jest.mock("@/lib/auth/hooks", () => ({
  useTokenExpiry: (...args: unknown[]) => mockUseTokenExpiry(...args),
  useCustomTokenRefresh: (...args: unknown[]) =>
    mockUseCustomTokenRefresh(...args),
  useSessionWatcher: (...args: unknown[]) => mockUseSessionWatcher(...args),
}));

describe("HealthBanner", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSWR.mockReturnValue({ error: undefined });
    mockUseCurrentUser.mockReturnValue({
      user: undefined,
      mutateUser: jest.fn(),
      userError: undefined,
    });
    mockUseTokenExpiry.mockReturnValue({
      expired: false,
      setupExpirationTimeout: jest.fn(),
    });
    mockUseCustomTokenRefresh.mockReturnValue(undefined);
    mockUseSessionWatcher.mockReturnValue({ sessionEnded: false });
  });

  it("renders nothing when the backend is healthy and the session is active", () => {
    const { container } = render(<HealthBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("does not show the logged-out modal when the session has not ended", () => {
    mockUseSessionWatcher.mockReturnValue({ sessionEnded: false });
    render(<HealthBanner />);
    expect(
      screen.queryByText(/you have been logged out/i)
    ).not.toBeInTheDocument();
  });

  it("shows the logged-out modal when the session has ended", () => {
    mockUseSessionWatcher.mockReturnValue({ sessionEnded: true });
    render(<HealthBanner />);
    expect(screen.getByText(/you have been logged out/i)).toBeInTheDocument();
  });

  it("shows the backend unavailable banner on a non-auth health error", () => {
    mockUseSWR.mockReturnValue({ error: new Error("network error") });
    render(<HealthBanner />);
    expect(
      screen.getByText(/the backend is currently unavailable/i)
    ).toBeInTheDocument();
  });

  it("does not show the backend banner when the token has expired", () => {
    mockUseSWR.mockReturnValue({ error: new Error("network error") });
    mockUseTokenExpiry.mockReturnValue({
      expired: true,
      setupExpirationTimeout: jest.fn(),
    });
    render(<HealthBanner />);
    expect(
      screen.queryByText(/the backend is currently unavailable/i)
    ).not.toBeInTheDocument();
  });
});
