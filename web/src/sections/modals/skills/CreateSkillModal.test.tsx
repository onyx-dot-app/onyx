import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import type { CustomSkill } from "@/lib/skills/types";

const mockCreateCustomSkill = jest.fn();
const mockInspectSkillBundle = jest.fn();

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  createCustomSkill: (...args: unknown[]) => mockCreateCustomSkill(...args),
  inspectSkillBundle: (...args: unknown[]) => mockInspectSkillBundle(...args),
}));

jest.mock("@/sections/skills/SkillBundlePicker", () => ({
  __esModule: true,
  default: ({ onChange }: { onChange: (bundle: object) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          file: new File(["bundle"], "skill.zip"),
          displayName: "skill.zip",
          source: "zip",
        })
      }
    >
      Select bundle
    </button>
  ),
}));

describe("CreateSkillModal", () => {
  beforeEach(() => {
    mockCreateCustomSkill.mockReset();
    mockInspectSkillBundle.mockReset();
  });

  it("confirms before creating a same-name skill disabled", async () => {
    const user = setupUser();
    const onCreated = jest.fn();
    const conflict = Object.assign(new Error("Name conflict"), {
      errorCode: "SKILL_NAME_CONFLICT",
    });
    const created = {
      id: "new-skill-id",
      name: "report-writer",
      enabled: false,
    } as CustomSkill;
    mockInspectSkillBundle.mockResolvedValue({ name: "report-writer" });
    mockCreateCustomSkill
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce(created);

    render(<CreateSkillModal open onClose={jest.fn()} onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Create another “report-writer” skill?")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The new skill will start disabled. You can switch which one is active from the Skills page."
      )
    ).toBeInTheDocument();
    expect(mockCreateCustomSkill).toHaveBeenCalledTimes(1);
    expect(mockCreateCustomSkill).toHaveBeenCalledWith(expect.any(File), true);
    expect(onCreated).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Create anyway" }));

    await waitFor(() => {
      expect(mockCreateCustomSkill).toHaveBeenNthCalledWith(
        1,
        expect.any(File),
        true
      );
      expect(mockCreateCustomSkill).toHaveBeenNthCalledWith(
        2,
        expect.any(File),
        false
      );
      expect(onCreated).toHaveBeenCalledWith(created);
    });
    expect(mockInspectSkillBundle).toHaveBeenCalledTimes(1);
  });

  it("returns to the upload without creating when confirmation is canceled", async () => {
    const user = setupUser();
    const onCreated = jest.fn();
    mockInspectSkillBundle.mockResolvedValue({ name: "report-writer" });
    mockCreateCustomSkill.mockRejectedValue(
      Object.assign(new Error("Name conflict"), {
        errorCode: "SKILL_NAME_CONFLICT",
      })
    );

    render(<CreateSkillModal open onClose={jest.fn()} onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await screen.findByText("Create another “report-writer” skill?");

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
    expect(mockCreateCustomSkill).toHaveBeenCalledTimes(1);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("creates immediately when the name is available", async () => {
    const user = setupUser();
    const onCreated = jest.fn();
    const created = {
      id: "new-skill-id",
      name: "available-skill",
      enabled: true,
    } as CustomSkill;
    mockInspectSkillBundle.mockResolvedValue({ name: "available-skill" });
    mockCreateCustomSkill.mockResolvedValue(created);

    render(<CreateSkillModal open onClose={jest.fn()} onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    expect(mockCreateCustomSkill).toHaveBeenCalledTimes(1);
    expect(mockCreateCustomSkill).toHaveBeenCalledWith(expect.any(File), true);
    expect(
      screen.queryByText(/Create another .* skill\?/)
    ).not.toBeInTheDocument();
  });
});
