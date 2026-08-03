import { render, screen, waitFor } from "@tests/setup/test-utils";
import UploadSkillModal from "./UploadSkillModal";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";

jest.mock("@/providers/UserProvider", () => ({
  useUser: jest.fn(),
}));

jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: jest.fn(() => ({ data: [] })),
}));

jest.mock("@/lib/skills/api", () => ({
  createCustomSkill: jest.fn(),
}));

const mockUseUser = useUser as jest.Mock;

function noop() {}

describe("UploadSkillModal publish default", () => {
  afterEach(() => jest.clearAllMocks());

  it("opens public-by-default for an admin whose permissions load after mount", async () => {
    // Mount closed while permissions are still loading (empty set) — the stale-capture case.
    mockUseUser.mockReturnValue({ permissions: [] });
    const { rerender } = render(
      <UploadSkillModal open={false} onClose={noop} onUploaded={noop} />
    );

    // Permissions resolve (global skill admin) and the dialog opens.
    mockUseUser.mockReturnValue({ permissions: [Permission.MANAGE_SKILLS] });
    rerender(<UploadSkillModal open onClose={noop} onUploaded={noop} />);

    await waitFor(() =>
      expect(
        screen.getByRole("tab", { name: "Your Organization" })
      ).toHaveAttribute("data-state", "active")
    );
  });

  it("opens private for a scoped manager without publish permission", async () => {
    mockUseUser.mockReturnValue({ permissions: [] });
    render(<UploadSkillModal open onClose={noop} onUploaded={noop} />);

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Groups" })).toHaveAttribute(
        "data-state",
        "active"
      )
    );
  });
});
