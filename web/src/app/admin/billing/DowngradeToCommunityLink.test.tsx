// The Community downgrade is offered only once a self-hosted deployment is
// locked out, and runs only after the consent screen is confirmed.
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { ApplicationStatus } from "@/lib/settings/types";
import DowngradeToCommunityLink from "@/app/admin/billing/DowngradeToCommunityLink";

const mockUseSettings = jest.fn();
const mockDowngradeToCommunity = jest.fn();
const mockFlags = { cloud: false };

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => mockUseSettings(),
}));

jest.mock("@/lib/billing", () => ({
  downgradeToCommunity: () => mockDowngradeToCommunity(),
}));

jest.mock("@/lib/constants", () => ({
  ...jest.requireActual("@/lib/constants"),
  get NEXT_PUBLIC_CLOUD_ENABLED() {
    return mockFlags.cloud;
  },
}));

function setStatus(applicationStatus: ApplicationStatus) {
  mockUseSettings.mockReturnValue({ application_status: applicationStatus });
}

describe("DowngradeToCommunityLink", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFlags.cloud = false;
  });

  it("is hidden while the deployment is not locked out", () => {
    setStatus(ApplicationStatus.ACTIVE);

    render(<DowngradeToCommunityLink />);

    expect(
      screen.queryByText("Downgrade to Community")
    ).not.toBeInTheDocument();
  });

  it("is hidden on cloud even when the tenant is gated", () => {
    mockFlags.cloud = true;
    setStatus(ApplicationStatus.GATED_ACCESS);

    render(<DowngradeToCommunityLink />);

    expect(
      screen.queryByText("Downgrade to Community")
    ).not.toBeInTheDocument();
  });

  it("downgrades only after the consent screen is confirmed", async () => {
    const user = setupUser();
    setStatus(ApplicationStatus.GATED_ACCESS);
    // Never settles, so the page reload on success stays out of the test.
    mockDowngradeToCommunity.mockReturnValue(new Promise(() => {}));

    render(<DowngradeToCommunityLink />);
    await user.click(screen.getByText("Downgrade to Community"));

    expect(screen.getByText(/Every connector becomes public/)).toBeVisible();
    expect(mockDowngradeToCommunity).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Downgrade" }));

    expect(mockDowngradeToCommunity).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Downgrading..." })
    ).toBeDisabled();
    // The request cannot be abandoned half way.
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
  });

  it("reports a failed downgrade and lets the admin retry", async () => {
    const user = setupUser();
    setStatus(ApplicationStatus.GATED_ACCESS);
    mockDowngradeToCommunity.mockRejectedValue(new Error("boom"));
    const toastError = jest.spyOn(toast, "error").mockReturnValue("toast-id");

    render(<DowngradeToCommunityLink />);
    await user.click(screen.getByText("Downgrade to Community"));
    await user.click(screen.getByRole("button", { name: "Downgrade" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Failed to downgrade", {
        description: "boom",
      })
    );
    expect(screen.getByRole("button", { name: "Downgrade" })).toBeEnabled();
  });
});
