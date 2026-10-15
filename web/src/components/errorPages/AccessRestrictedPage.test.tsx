// Only an admin may start the Community downgrade from the lock page.
import { render, screen } from "@tests/setup/test-utils";
import { ApplicationStatus } from "@/lib/settings/types";
import AccessRestrictedPage from "@/components/errorPages/AccessRestrictedPage";

const mockUseUser = jest.fn();

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => mockUseUser(),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    application_status: ApplicationStatus.GATED_ACCESS,
    appName: "Onyx",
  }),
}));

jest.mock("@/hooks/useLicense", () => ({
  useLicense: () => ({ data: { has_license: true } }),
}));

jest.mock("@/lib/constants", () => ({
  ...jest.requireActual("@/lib/constants"),
  NEXT_PUBLIC_CLOUD_ENABLED: false,
}));

describe("AccessRestrictedPage", () => {
  it.each([
    [true, 1],
    [false, 0],
  ])("offers the downgrade when isAdmin is %s", (isAdmin, expectedCount) => {
    mockUseUser.mockReturnValue({ isAdmin });

    render(<AccessRestrictedPage />);

    expect(
      screen.queryAllByRole("button", { name: "Downgrade to Community" })
    ).toHaveLength(expectedCount);
    expect(screen.getByRole("button", { name: "Log out" })).toBeVisible();
  });
});
