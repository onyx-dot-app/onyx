import React from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { RedirectError } from "@/lib/fetcher";
import AppHealthBanner from "./AppHealthBanner";

const mockLogout = jest.fn();
const mockUseSWR = jest.fn();
const mockUseCurrentUser = jest.fn();
const mockUsePathname = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

jest.mock("@/hooks/useCurrentUser", () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}));

jest.mock("@/lib/user", () => ({
  logout: (...args: unknown[]) => mockLogout(...args),
}));

describe("AppHealthBanner logout handling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLogout.mockResolvedValue(undefined);
    mockUseSWR.mockReturnValue({ error: undefined });
    mockUseCurrentUser.mockReturnValue({
      user: undefined,
      mutateUser: jest.fn(),
      userError: undefined,
    });
    mockUsePathname.mockReturnValue("/auth/login");
  });

  it("does not show the logged-out modal or call logout on auth pages after a 403", async () => {
    mockUseCurrentUser.mockReturnValue({
      user: undefined,
      mutateUser: jest.fn(),
      userError: {
        status: 403,
      },
    });

    render(<AppHealthBanner />);

    await waitFor(() => {
      expect(mockLogout).not.toHaveBeenCalled();
    });

    expect(
      screen.queryByText(/you have been logged out/i)
    ).not.toBeInTheDocument();
  });

  it("does not show the logged-out modal on a fresh unauthenticated load", async () => {
    mockUsePathname.mockReturnValue("/");
    mockUseSWR.mockReturnValue({
      error: new RedirectError("auth redirect", 403, {}),
    });

    render(<AppHealthBanner />);

    await waitFor(() => {
      expect(mockLogout).not.toHaveBeenCalled();
    });

    expect(
      screen.queryByText(/you have been logged out/i)
    ).not.toBeInTheDocument();
  });

  it("shows the logged-out modal after a 403 when a user was previously loaded", async () => {
    mockUsePathname.mockReturnValue("/chat");
    mockUseCurrentUser.mockReturnValue({
      user: {
        id: "user-1",
        email: "a@example.com",
      },
      mutateUser: jest.fn(),
      userError: {
        status: 403,
      },
    });

    render(<AppHealthBanner />);

    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalled();
    });

    expect(
      await screen.findByText(/you have been logged out/i)
    ).toBeInTheDocument();
  });
});
