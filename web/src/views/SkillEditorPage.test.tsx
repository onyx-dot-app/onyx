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

const mockCreateCustomSkillFromEditor = jest.fn();
const mockRouterReplace = jest.fn();
const mockRouterPush = jest.fn();
const mockGetSkillCreationDraft = jest.fn();
const mockDiscardSkillCreationDraft = jest.fn();
const mockMutate = jest.fn();

async function fillRequiredFields(user: ReturnType<typeof setupUser>) {
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
}

jest.mock("next/navigation", () => ({
  usePathname: () => "/craft/v1/skills/new",
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace,
  }),
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("@/lib/skills/creationDraft", () => ({
  getSkillCreationDraft: (...args: unknown[]) =>
    mockGetSkillCreationDraft(...args),
  discardSkillCreationDraft: (...args: unknown[]) =>
    mockDiscardSkillCreationDraft(...args),
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
    mockRouterPush.mockReset();
    mockGetSkillCreationDraft.mockReset();
    mockDiscardSkillCreationDraft.mockReset();
    mockMutate.mockReset();
    mockMutate.mockResolvedValue(undefined);
  });

  it("navigates after creation even when the skill-list refresh fails", async () => {
    const user = setupUser();
    const consoleError = jest.spyOn(console, "error").mockImplementation();
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      id: "created-id",
      name: "report-writer",
      enabled: true,
    } as SkillEditableDetail);
    mockMutate.mockRejectedValue(new Error("Refresh failed"));

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/skills")
    );
    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith(
        "Failed to refresh skill list after creation",
        expect.any(Error)
      )
    );
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(1);
    consoleError.mockRestore();
  });

  it("prefills an uploaded draft without creating it until Save", async () => {
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

    expect(screen.getByDisplayValue("report-writer")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Writes reports")).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("Write the requested report.")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Have an existing skill?")
    ).not.toBeInTheDocument();
    expect(mockCreateCustomSkillFromEditor).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Save" }));

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
    expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/skills");
  });

  it("confirms before canceling a create page with unsaved changes", async () => {
    const user = setupUser();
    render(<SkillEditorPage />);

    expect(screen.getByText("Have an existing skill?")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Name your skill"), "draft");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(mockRouterPush).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByText("Discard unsaved changes?")
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("draft")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterPush).toHaveBeenCalledWith("/craft/v1/skills");
  });

  it("warns before unloading a create page with unsaved changes", async () => {
    const user = setupUser();
    render(<SkillEditorPage />);
    await user.type(screen.getByPlaceholderText("Name your skill"), "draft");

    const event = new Event("beforeunload", { cancelable: true });
    act(() => window.dispatchEvent(event));

    expect(event.defaultPrevented).toBe(true);
  });

  it("restores browser history when discarding is canceled", async () => {
    const user = setupUser();
    const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
    const forward = jest
      .spyOn(window.history, "forward")
      .mockImplementation(() => undefined);
    render(<SkillEditorPage />);
    await user.type(screen.getByPlaceholderText("Name your skill"), "draft");

    act(() => window.dispatchEvent(new PopStateEvent("popstate")));

    expect(confirm).toHaveBeenCalledWith("Discard unsaved changes?");
    expect(forward).toHaveBeenCalledTimes(1);

    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    expect(confirm).toHaveBeenCalledTimes(1);

    confirm.mockRestore();
    forward.mockRestore();
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
    await user.click(screen.getByRole("button", { name: "Save" }));

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
      expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/skills");
    });
    expect(
      screen.queryByText("Create another “report-writer” skill?")
    ).not.toBeInTheDocument();
  });

  it("keeps the confirmation open when disabled creation fails", async () => {
    const user = setupUser();
    const conflict = Object.assign(new Error("Name conflict"), {
      errorCode: "SKILL_NAME_CONFLICT",
    });
    const retry = deferred<SkillEditableDetail>();
    mockCreateCustomSkillFromEditor
      .mockRejectedValueOnce(conflict)
      .mockReturnValueOnce(retry.promise);

    render(<SkillEditorPage />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Save" }));
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
  });
});
