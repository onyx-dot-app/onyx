import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillEditorPage from "@/views/SkillEditorPage";
import type { SkillEditableDetail } from "@/lib/skills/types";

const mockCreateCustomSkillFromEditor = jest.fn();
const mockRouterReplace = jest.fn();

jest.mock("next/navigation", () => ({
  usePathname: () => "/craft/v1/skills/new",
  useRouter: () => ({
    push: jest.fn(),
    replace: mockRouterReplace,
  }),
}));

jest.mock("@/sections/modals/skills/ShareSkillModal", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  createCustomSkillFromEditor: (...args: unknown[]) =>
    mockCreateCustomSkillFromEditor(...args),
}));

jest.mock("@/sections/skills/SkillFilesPicker", () => ({
  __esModule: true,
  default: () => null,
}));

describe("SkillEditorPage creation", () => {
  beforeEach(() => {
    mockCreateCustomSkillFromEditor.mockReset();
    mockRouterReplace.mockReset();
  });

  it("requires confirmation before retrying a same-name creation disabled", async () => {
    const user = setupUser();
    const conflict = Object.assign(new Error("Name conflict"), {
      errorCode: "SKILL_NAME_CONFLICT",
    });
    const created = {
      id: "created-id",
      name: "report-writer",
      enabled: false,
    } as SkillEditableDetail;
    mockCreateCustomSkillFromEditor
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce(created);

    render(<SkillEditorPage />);
    await user.type(
      screen.getByPlaceholderText("Name your skill"),
      "report-writer"
    );
    await user.type(
      screen.getByPlaceholderText("What does this skill help with?"),
      "Writes reports"
    );
    await user.type(
      screen.getByPlaceholderText("Write the skill instructions."),
      "Write the requested report."
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Create another “report-writer” skill?")
    ).toBeInTheDocument();
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(1);
    expect(mockCreateCustomSkillFromEditor).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "report-writer",
        auto_enable: true,
      }),
      undefined
    );
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Create anyway" }));

    await waitFor(() => {
      expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(2);
      expect(mockCreateCustomSkillFromEditor).toHaveBeenLastCalledWith(
        expect.objectContaining({
          name: "report-writer",
          auto_enable: false,
        }),
        undefined
      );
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/craft/v1/skills/edit/created-id"
      );
    });
  });
});
