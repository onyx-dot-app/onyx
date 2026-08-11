// Guards the account chip's loading contract: skeleton while the user is
// unresolved, "Anonymous" only for a resolved signed-out user.
import { render, screen } from "@tests/setup/test-utils";
import AccountPopover from "./AccountPopover";
import { useUser } from "@/providers/UserProvider";
import { User } from "@/lib/types";

// Factory mock so the loading branch is drivable. The global stub pins
// isUserLoading to false.
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
jest.mock("@/hooks/useAppFocus", () => ({
  __esModule: true,
  default: () => ({ isUserSettings: () => false }),
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

function setUser(user: User | null, isUserLoading: boolean) {
  mockedUseUser.mockReturnValue({
    user,
    isUserLoading,
  } as ReturnType<typeof useUser>);
}

it("shows a skeleton instead of Anonymous while the user is unresolved", () => {
  setUser(null, true);
  render(<AccountPopover />);
  expect(screen.queryByText("Anonymous")).not.toBeInTheDocument();
  // The trigger button is replaced entirely, not rendered empty.
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows Anonymous for a resolved signed-out user", () => {
  setUser(null, false);
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
    false
  );
  render(<AccountPopover />);
  expect(screen.getByText("John")).toBeInTheDocument();
});
