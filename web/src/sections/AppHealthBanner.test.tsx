import React from "react";
import { beforeEach, describe, expect, it, mock } from "bun:test";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { RedirectError } from "@/lib/fetcher";
import AppHealthBanner from "./AppHealthBanner";

const mockLogout = mock();
const mockUseSWR = mock();
const mockUseCurrentUser = mock();
const mockUsePathname = mock();

// Partial mock: keep the rest of `swr` intact, override only the default export.
// Replaces jest.requireActual + jest.mock by importing the real module first,
// then spreading it into the mock factory.
const actualSWR = await import("swr");
mock.module("swr", () => ({
  __esModule: true,
  ...actualSWR,
  default: (...args: unknown[]) => mockUseSWR(...args),
}));

mock.module("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: mock(),
  }),
}));

mock.module("@/hooks/useCurrentUser", () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}));

mock.module("@/lib/user", () => ({
  logout: (...args: unknown[]) => mockLogout(...args),
}));

describe("AppHealthBanner logout handling", () => {
  beforeEach(() => {
    mockLogout.mockReset();
    mockUseSWR.mockReset();
    mockUseCurrentUser.mockReset();
    mockUsePathname.mockReset();

    mockLogout.mockResolvedValue(undefined);
    mockUseSWR.mockReturnValue({ error: undefined });
    mockUseCurrentUser.mockReturnValue({
      user: undefined,
      mutateUser: mock(),
      userError: undefined,
    });
    mockUsePathname.mockReturnValue("/auth/login");
  });

  it("does not show the logged-out modal or call logout on auth pages after a 403", async () => {
    mockUseCurrentUser.mockReturnValue({
      user: undefined,
      mutateUser: mock(),
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
      mutateUser: mock(),
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
