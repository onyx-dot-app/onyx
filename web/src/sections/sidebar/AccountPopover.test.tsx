// The chip shows a skeleton while unresolved and "Anonymous" only when resolved signed-out.
import { render, screen } from "@tests/setup/test-utils";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { useUser } from "@/providers/UserProvider";
import { User } from "@/lib/types";

// Factory mock: the global stub pins userResolution to "resolved".
jest.mock("@/providers/UserProvider", () => ({ useUser: jest.fn() }));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/app",
  useSearchParams: () => new URLSearchParams(),
}));
jest.mock("@/sections/sidebar/NotificationsPopover", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/lib/position/hooks", () => ({
  __esModule: true,
  useAppPosition: () => ({ isUserSettings: () => false }),
}));
jest.mock("@/hooks/useScreenSize", () => ({
  __esModule: true,
  default: () => ({ isMobile: false }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ vectorDbEnabled: false }),
}));
jest.mock("@/hooks/useNotifications", () => ({
  useNotificationSummary: () => ({ undismissedCount: 0, refresh: jest.fn() }),
}));

const mockedUseUser = jest.mocked(useUser);

function setUser(
  user: User | null,
  userResolution: "loading" | "unavailable" | "resolved"
) {
  mockedUseUser.mockReturnValue({
    user,
    userResolution,
  } as ReturnType<typeof useUser>);
}

it("shows a skeleton instead of Anonymous while the user is unresolved", () => {
  setUser(null, "loading");
  render(<AccountPopover />);
  expect(screen.queryByText("Anonymous")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows a neutral label, not Anonymous, when the user is unavailable", () => {
  setUser(null, "unavailable");
  render(<AccountPopover />);
  expect(screen.getByText("Account")).toBeInTheDocument();
  expect(screen.queryByText("Anonymous")).not.toBeInTheDocument();
});

it("shows Anonymous for a resolved signed-out user", () => {
  setUser(null, "resolved");
  render(<AccountPopover />);
  expect(screen.getByText("Anonymous")).toBeInTheDocument();
});

it("shows the user's name once resolved", () => {
  setUser(
    {
      id: "u1",
      email: "john@example.com",
      personalization: { name: "John" },
    } as unknown as User,
    "resolved"
  );
  render(<AccountPopover />);
  expect(screen.getByText("John")).toBeInTheDocument();
});
