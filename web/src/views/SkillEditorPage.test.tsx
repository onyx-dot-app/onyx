import type { ComponentProps } from "react";
import type ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import type SkillFilesPicker from "@/sections/skills/SkillFilesPicker";
import {
  SkillMergeLimitError,
  type PreparedSkillFilesUpload,
} from "@/lib/skills/bundleUpload";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SkillEditorPage from "@/views/SkillEditorPage";
import type { SkillEditableDetail } from "@/lib/skills/types";
import { toast } from "@opal/layouts";
import messages from "@/i18n/messages/en.json";

const mockCreateCustomSkillFromEditor = jest.fn();
const mockUploadUserSkillFiles = jest.fn();
const merged = new File(["zip"], "skill-files.zip");
const mockMerge = jest.fn();
jest.mock("@/lib/skills/bundleUpload", () => ({
  ...jest.requireActual("@/lib/skills/bundleUpload"),
  mergeSkillFilesUploads: (...args: unknown[]) => mockMerge(...args),
}));
const mockRouterReplace = jest.fn();
const mockGetSkillCreationDraft = jest.fn();
const mockDiscardSkillCreationDraft = jest.fn();
const mockMutate = jest.fn();
const mockRefreshSkill = jest.fn();
const mockUseSWR = jest.fn();

async function fillRequiredFields(user: ReturnType<typeof setupUser>) {
  const editor = screen.getByRole("textbox", { name: "SKILL.md" });
  await user.clear(editor);
  await user.click(editor);
  await user.paste(
    '---\nname: "report-writer"\ndescription: "Writes reports"\n---\n\nWrite the requested report.'
  );
}

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app/customize/skills/new",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    replace: mockRouterReplace,
  }),
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
  useSWRConfig: () => ({ mutate: mockMutate, cache: new Map() }),
}));

jest.mock("@/lib/skills/creationDraft", () => ({
  getSkillCreationDraft: (...args: unknown[]) =>
    mockGetSkillCreationDraft(...args),
  discardSkillCreationDraft: (...args: unknown[]) =>
    mockDiscardSkillCreationDraft(...args),
}));

jest.mock("@/sections/modals/skills/ShareSkillModal", () => ({
  __esModule: true,
  default: (props: ComponentProps<typeof ShareSkillModal>) => {
    if (!props.open) return null;
    if (props.mode === "edit") return null;
    return (
      <button
        type="button"
        onClick={() => {
          props.onSaveDraft({ ...props.draft, public_permission: "VIEWER" });
          props.onClose();
        }}
      >
        Choose organization access
      </button>
    );
  },
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  createCustomSkillFromEditor: (...args: unknown[]) =>
    mockCreateCustomSkillFromEditor(...args),
  uploadUserSkillFiles: (...args: unknown[]) =>
    mockUploadUserSkillFiles(...args),
}));

const mockPickedUploads: PreparedSkillFilesUpload[] = [];
jest.mock("@/sections/skills/SkillFilesPicker", () => ({
  __esModule: true,
  default: (props: ComponentProps<typeof SkillFilesPicker>) => (
    <button
      type="button"
      onClick={() => {
        const next = mockPickedUploads.shift();
        if (next) props.onChange(next);
      }}
    >
      Pick a file
    </button>
  ),
}));

describe("SkillEditorPage", () => {
  beforeEach(() => {
    mockCreateCustomSkillFromEditor.mockReset();
    mockUploadUserSkillFiles.mockReset();
    mockMerge.mockReset();
    mockMerge.mockImplementation(async (uploads: unknown[]) =>
      uploads.length > 0 ? merged : undefined
    );
    mockPickedUploads.length = 0;
    mockRouterReplace.mockReset();
    window.history.replaceState(null, "", "/");
    mockGetSkillCreationDraft.mockReset();
    mockDiscardSkillCreationDraft.mockReset();
    mockMutate.mockReset();
    mockMutate.mockResolvedValue(undefined);
    mockRefreshSkill.mockReset();
    mockUseSWR.mockReset();
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
  });

  afterEach(() => jest.restoreAllMocks());

  it("includes draft sharing settings in the creation request", async () => {
    const user = setupUser();
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      name: "report-writer",
    });
    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Edit sharing" }));
    await user.click(
      screen.getByRole("button", { name: "Choose organization access" })
    );
    expect(mockCreateCustomSkillFromEditor).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledWith(
      expect.objectContaining({
        sharing: {
          public_permission: "VIEWER",
          user_shares: [],
          group_shares: [],
        },
      }),
      undefined
    );
  });

  it("reports a failed skill-list refresh and still opens the new skill", async () => {
    const user = setupUser();
    const toastError = jest.spyOn(toast, "error");
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      id: "created-id",
      name: "report-writer",
      enabled: true,
    } as SkillEditableDetail);
    mockMutate.mockRejectedValue(new Error("Refresh failed"));

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/app/customize/skills/created-id"
      )
    );
    expect(toastError).toHaveBeenCalledWith(
      messages.skills.page.toasts.listRefreshFailed
    );
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(1);
    toastError.mockRestore();
  });

  it("prefills an uploaded draft without creating it until Create", async () => {
    const user = setupUser();
    const upload = new File(["bundle"], "report-writer.zip");
    mockGetSkillCreationDraft.mockReturnValue({
      contents: {
        name: "report-writer",
        description: "Writes reports",
        instructions_markdown: "Write the requested report.",
        files: [{ path: "SKILL.md", size: 64 }],
      },
      upload: {
        file: upload,
        displayName: upload.name,
        entries: [{ path: "SKILL.md", size: 64 }],
        containsSkillMd: true,
      },
    });
    const created = {
      id: "created-id",
      name: "report-writer",
      enabled: true,
    } as SkillEditableDetail;
    mockCreateCustomSkillFromEditor.mockResolvedValue(created);

    render(<SkillEditorPage draftId="draft-id" />);

    expect(screen.getByRole("textbox", { name: "SKILL.md" })).toHaveValue(
      '---\nname: "report-writer"\ndescription: "Writes reports"\n---\n\nWrite the requested report.'
    );
    expect(mockCreateCustomSkillFromEditor).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledWith(
        {
          name: "report-writer",
          description: "Writes reports",
          instructions_markdown: "Write the requested report.",
          auto_enable: true,
        },
        upload
      )
    );
    expect(mockDiscardSkillCreationDraft).toHaveBeenCalledWith("draft-id");
    expect(mockRouterReplace).toHaveBeenCalledWith(
      "/app/customize/skills/created-id"
    );
  });

  it("creates the skill with every added file and its sharing in one request", async () => {
    const user = setupUser();
    mockPickedUploads.push(
      {
        file: new File(["a"], "a.txt"),
        displayName: "a.txt",
        entries: [{ path: "a.txt", size: 1 }],
        containsSkillMd: false,
      },
      {
        file: new File(["b"], "b.txt"),
        displayName: "b.txt",
        entries: [{ path: "b.txt", size: 1 }],
        containsSkillMd: false,
      }
    );
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      id: "created-id",
      name: "report-writer",
    } as SkillEditableDetail);

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Edit sharing" }));
    await user.click(
      screen.getByRole("button", { name: "Choose organization access" })
    );
    await user.click(screen.getByRole("button", { name: "Pick a file" }));
    await user.click(screen.getByRole("button", { name: "Pick a file" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/app/customize/skills/created-id"
      )
    );
    expect(mockMerge).toHaveBeenCalledWith(
      [
        expect.objectContaining({ displayName: "a.txt" }),
        expect.objectContaining({ displayName: "b.txt" }),
      ],
      new Set()
    );
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(1);
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledWith(
      expect.objectContaining({
        sharing: expect.objectContaining({ public_permission: "VIEWER" }),
      }),
      merged
    );
    expect(mockUploadUserSkillFiles).not.toHaveBeenCalled();
  });

  it("says in the user's language when the files pass the skill limit", async () => {
    const user = setupUser();
    const toastError = jest.spyOn(toast, "error");
    jest.spyOn(console, "error").mockImplementation();
    mockPickedUploads.push({
      file: new File(["a"], "a.txt"),
      displayName: "a.txt",
      entries: [{ path: "a.txt", size: 1 }],
      containsSkillMd: false,
    });
    mockMerge.mockRejectedValue(new SkillMergeLimitError("files", 5_000));

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Pick a file" }));
    mockPickedUploads.push({
      file: new File(["b"], "b.txt"),
      displayName: "b.txt",
      entries: [{ path: "b.txt", size: 1 }],
      containsSkillMd: false,
    });
    await user.click(screen.getByRole("button", { name: "Pick a file" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "A skill can hold up to 5,000 files. Remove some files, then select Create."
      )
    );
    expect(mockCreateCustomSkillFromEditor).not.toHaveBeenCalled();
  });

  it("does not send an upload whose files were all removed", async () => {
    const user = setupUser();
    mockPickedUploads.push({
      file: new File(["zip"], "references.zip"),
      displayName: "references.zip",
      entries: null,
      containsSkillMd: false,
    });
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      id: "created-id",
      name: "report-writer",
      current_version_id: "v1",
    } as SkillEditableDetail);

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Pick a file" }));
    await user.click(screen.getByRole("button", { name: "references.zip" }));
    await user.click(
      screen.getByRole("button", { name: "Remove references.zip" })
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledWith(
        expect.objectContaining({ name: "report-writer" }),
        undefined
      )
    );
    expect(mockUploadUserSkillFiles).not.toHaveBeenCalled();
  });

  it("confirms before canceling a create page with unsaved changes", async () => {
    const user = setupUser();
    render(<SkillEditorPage />);

    await user.type(
      screen.getByRole("textbox", { name: "SKILL.md" }),
      "Draft notes"
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByText("Discard unsaved changes?")
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "SKILL.md" })
    ).toHaveDisplayValue(/Draft notes/);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/app/customize/skills");
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
    await fillRequiredFields(user);
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
        "/app/customize/skills/created-id"
      );
    });
    expect(
      screen.queryByText("Create another “report-writer” skill?")
    ).not.toBeInTheDocument();
  });

  it("keeps the confirmation open when disabled creation fails", async () => {
    const user = setupUser();
    const consoleError = jest.spyOn(console, "error").mockImplementation();
    const conflict = Object.assign(new Error("Name conflict"), {
      errorCode: "SKILL_NAME_CONFLICT",
    });
    const retry = deferred<SkillEditableDetail>();
    mockCreateCustomSkillFromEditor
      .mockRejectedValueOnce(conflict)
      .mockReturnValueOnce(retry.promise);

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Create" }));
    await user.click(
      await screen.findByRole("button", { name: "Create anyway" })
    );

    expect(screen.getByRole("button", { name: "Creating..." })).toBeDisabled();
    expect(
      screen.getByText("Create another “report-writer” skill?")
    ).toBeInTheDocument();

    await act(async () => {
      retry.reject(new Error("Creation failed"));
      await retry.promise.catch(() => undefined);
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Create anyway" })
      ).toBeEnabled()
    );
    expect(
      screen.getByText("Create another “report-writer” skill?")
    ).toBeInTheDocument();
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(2);
    expect(consoleError).toHaveBeenCalledWith(
      "Failed to save skill",
      expect.any(Error)
    );
  });
});
