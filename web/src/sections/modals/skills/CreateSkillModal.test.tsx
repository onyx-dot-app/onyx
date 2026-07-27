import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import type { SkillBundleContents } from "@/lib/skills/types";

const mockInspectSkillBundle = jest.fn();

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
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

const inspectedContents: SkillBundleContents = {
  name: "report-writer",
  description: "Writes polished reports",
  instructions_markdown: "# Report writer\n\nWrite the requested report.",
  files: [
    { path: "SKILL.md", size: 128 },
    { path: "references/style.md", size: 64 },
  ],
};

describe("CreateSkillModal", () => {
  beforeEach(() => {
    mockInspectSkillBundle.mockReset();
  });

  afterEach(() => jest.restoreAllMocks());

  it("inspects the upload and passes an unsaved editor draft onward", async () => {
    const user = setupUser();
    const onContinue = jest.fn();
    mockInspectSkillBundle.mockResolvedValue(inspectedContents);

    render(
      <CreateSkillModal open onClose={jest.fn()} onContinue={onContinue} />
    );
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Review skill" }));

    await waitFor(() => expect(onContinue).toHaveBeenCalledTimes(1));
    const draft = onContinue.mock.calls[0]![0];
    expect(draft.contents).toEqual(inspectedContents);
    expect(draft.upload).toEqual(
      expect.objectContaining({
        displayName: "skill.zip",
        entries: inspectedContents.files,
        containsSkillMd: true,
      })
    );
    expect(draft.upload.file).toBeInstanceOf(File);
    expect(mockInspectSkillBundle).toHaveBeenCalledWith(draft.upload.file);
    expect(screen.getByRole("button", { name: "Review skill" })).toBeDisabled();
  });

  it("keeps the modal open and reports inspection failures", async () => {
    const user = setupUser();
    const onContinue = jest.fn();
    const consoleError = jest.spyOn(console, "error").mockImplementation();
    mockInspectSkillBundle.mockRejectedValue(
      new Error("SKILL.md is missing its description")
    );

    render(
      <CreateSkillModal open onClose={jest.fn()} onContinue={onContinue} />
    );
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Review skill" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "SKILL.md is missing its description"
    );
    expect(onContinue).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled();
    expect(consoleError).toHaveBeenCalledWith(
      "Failed to inspect skill bundle",
      expect.any(Error)
    );
  });

  it("keeps a rejected inspected draft in the upload modal", async () => {
    const user = setupUser();
    const onContinue = jest.fn();
    const validationMessage =
      "App “Acme CRM” already has an associated skill named “report-writer”. Upload a skill with a different name.";
    mockInspectSkillBundle.mockResolvedValue(inspectedContents);

    render(
      <CreateSkillModal
        open
        onClose={jest.fn()}
        onContinue={onContinue}
        validateDraft={() => validationMessage}
      />
    );
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Review skill" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      validationMessage
    );
    expect(onContinue).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review skill" })).toBeEnabled();
  });

  it("cannot submit again or close while inspection is pending", async () => {
    const user = setupUser();
    const inspection = deferred<SkillBundleContents>();
    const onClose = jest.fn();
    mockInspectSkillBundle.mockReturnValue(inspection.promise);

    render(<CreateSkillModal open onClose={onClose} onContinue={jest.fn()} />);
    await user.click(screen.getByRole("button", { name: "Select bundle" }));
    await user.click(screen.getByRole("button", { name: "Review skill" }));

    expect(screen.getByRole("button", { name: "Opening…" })).toBeDisabled();
    expect(mockInspectSkillBundle).toHaveBeenCalledTimes(1);
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      inspection.resolve(inspectedContents);
      await inspection.promise;
    });
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
