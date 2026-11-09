import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import type { SkillSharingDraft } from "@/lib/skills/sharing";
import type { SkillBundleContents } from "@/lib/skills/types";

const mockInspectSkillBundle = jest.fn();
const mockUploadSkillBundles = jest.fn();

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  inspectSkillBundle: (...args: unknown[]) => mockInspectSkillBundle(...args),
  uploadSkillBundles: (...args: unknown[]) => mockUploadSkillBundles(...args),
}));

jest.mock("@/sections/skills/SkillBundlePicker", () => ({
  __esModule: true,
  default: ({
    onChange,
    onBatchChange,
  }: {
    onChange: (bundle: object) => void;
    onBatchChange?: (files: File[]) => void;
  }) => (
    <>
      {onBatchChange && (
        <button
          onClick={() =>
            onBatchChange([
              new File(["zip"], "alpha.zip"),
              new File(["zip"], "beta.zip"),
            ])
          }
        >
          Select multiple bundles
        </button>
      )}
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
    </>
  ),
}));

jest.mock("@/sections/modals/skills/ShareSkillModal", () => ({
  __esModule: true,
  default: ({
    draft,
    onSaveDraft,
    onClose,
  }: {
    draft: SkillSharingDraft;
    onSaveDraft: (draft: SkillSharingDraft) => void;
    onClose: () => void;
  }) => (
    <button
      onClick={() => {
        onSaveDraft({ ...draft, public_permission: "VIEWER" });
        onClose();
      }}
    >
      Share uploaded skills with organization
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
    mockUploadSkillBundles.mockReset();
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

  it("uploads multiple bundles with one access configuration and reports failures", async () => {
    const user = setupUser();
    const onImported = jest.fn();
    const onContinue = jest.fn();
    mockUploadSkillBundles.mockResolvedValue({
      imported: [
        { skill: { id: "alpha", name: "alpha" }, disabled_reason: null },
      ],
      not_imported: [
        { path: "beta.zip", name: "beta.zip", reason: "Invalid SKILL.md" },
      ],
    });
    render(
      <CreateSkillModal
        open
        onClose={jest.fn()}
        onContinue={onContinue}
        onImported={onImported}
      />
    );
    await user.click(
      screen.getByRole("button", { name: "Select multiple bundles" })
    );
    await user.click(screen.getByRole("button", { name: "Configure access" }));
    await user.click(
      screen.getByRole("button", {
        name: "Share uploaded skills with organization",
      })
    );
    expect(
      screen.getByText("Everyone in the organization can access these skills.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import 2 skills" }));
    await waitFor(() =>
      expect(mockUploadSkillBundles).toHaveBeenCalledWith(
        [
          expect.objectContaining({ name: "alpha.zip" }),
          expect.objectContaining({ name: "beta.zip" }),
        ],
        expect.objectContaining({
          public_permission: undefined,
          user_shares: [],
          group_shares: [],
        })
      )
    );
    expect(
      await screen.findByText("1 skill imported. 1 failed.")
    ).toBeInTheDocument();
    expect(screen.getByText("beta.zip: Invalid SKILL.md")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(onContinue).not.toHaveBeenCalled();
    expect(mockInspectSkillBundle).not.toHaveBeenCalled();
  });

  it("starts a fresh batch when the dialog is reopened", async () => {
    const user = setupUser();
    mockUploadSkillBundles.mockResolvedValue({
      imported: [
        { skill: { id: "alpha", name: "alpha" }, disabled_reason: null },
      ],
      not_imported: [],
    });
    const props = {
      onClose: jest.fn(),
      onContinue: jest.fn(),
      onImported: jest.fn(),
    };
    const { rerender } = render(<CreateSkillModal open {...props} />);
    await user.click(
      screen.getByRole("button", { name: "Select multiple bundles" })
    );
    await user.click(screen.getByRole("button", { name: "Import 2 skills" }));
    await screen.findByRole("button", { name: "Done" });
    rerender(<CreateSkillModal open={false} {...props} />);
    rerender(<CreateSkillModal open {...props} />);
    expect(
      screen.getByRole("button", { name: "Select multiple bundles" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Done" })
    ).not.toBeInTheDocument();
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
