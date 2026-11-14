import type { ComponentProps } from "react";
import type ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
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
import { SWR_KEYS } from "@/lib/swr-keys";

const mockCreateCustomSkillFromEditor = jest.fn();
const mockDeleteUserSkill = jest.fn();
const mockPatchUserSkill = jest.fn();
const mockRemoveUserSkillFile = jest.fn();
const mockRouterReplace = jest.fn();
const mockGetSkillCreationDraft = jest.fn();
const mockDiscardSkillCreationDraft = jest.fn();
const mockMutate = jest.fn();
const mockRefreshSkill = jest.fn();
const mockUseSWR = jest.fn();
let mockRestoredSkill: SkillEditableDetail;

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

function existingSkill(
  overrides: Partial<SkillEditableDetail> = {}
): SkillEditableDetail {
  return {
    source: "custom",
    id: "existing-id",
    name: "report-writer",
    description: "Writes reports",
    instructions_markdown: "Write the requested report.",
    files: [],
    is_available: true,
    unavailable_reason: null,
    is_valid: true,
    is_personal: true,
    enabled: true,
    can_toggle: true,
    installation_policy: "AVAILABLE",
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    group_summaries: [],
    required_for_user: false,
    author_user_id: "author-id",
    author_email: "author@example.com",
    owner: { id: "author-id", email: "author@example.com" },
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: null,
    user_permission: "OWNER",
    external_app: null,
    current_version_id: "version-1",
    current_version_number: 1,
    published_version_number: null,
    pending_version_number: null,
    ...overrides,
  };
}

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/craft/v1/skills/new",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    replace: mockRouterReplace,
  }),
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: (...args: unknown[]) => mockUseSWR(...args),
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
  default: (props: ComponentProps<typeof ShareSkillModal>) => {
    if (!props.open) return null;
    if (props.mode === "edit") {
      return (
        <button
          type="button"
          disabled={props.restoreBlocked}
          onClick={() => props.onVersionRestored?.(mockRestoredSkill)}
        >
          Restore version 1
        </button>
      );
    }
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
  deleteUserSkill: (...args: unknown[]) => mockDeleteUserSkill(...args),
  patchUserSkill: (...args: unknown[]) => mockPatchUserSkill(...args),
  removeUserSkillFile: (...args: unknown[]) => mockRemoveUserSkillFile(...args),
}));

jest.mock("@/sections/skills/SkillFilesPicker", () => ({
  __esModule: true,
  default: () => null,
}));

describe("SkillEditorPage", () => {
  beforeEach(() => {
    mockCreateCustomSkillFromEditor.mockReset();
    mockDeleteUserSkill.mockReset();
    mockDeleteUserSkill.mockResolvedValue(undefined);
    mockPatchUserSkill.mockReset();
    mockRemoveUserSkillFile.mockReset();
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
    await user.click(screen.getByRole("button", { name: "Save" }));
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
        "Failed to refresh skill data after creation",
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

  it("creates an app-associated skill disabled and returns to that app", async () => {
    const user = setupUser();
    const appRefresh = deferred<void>();
    mockCreateCustomSkillFromEditor.mockResolvedValue({
      id: "created-id",
      name: "report-writer",
      enabled: false,
    } as SkillEditableDetail);
    mockMutate.mockImplementation((key: string) =>
      key === SWR_KEYS.buildExternalAppsAdmin
        ? appRefresh.promise
        : Promise.resolve()
    );

    render(<SkillEditorPage externalAppId={42} externalAppName="Acme CRM" />);
    expect(
      screen.getByText("Add an organization skill to app “Acme CRM”")
    ).toBeInTheDocument();
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledWith(
        {
          name: "report-writer",
          description: "Writes reports",
          instructions_markdown: "Write the requested report.",
          auto_enable: false,
          external_app_id: 42,
        },
        undefined
      )
    );
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await act(async () => {
      appRefresh.resolve();
      await appRefresh.promise;
    });
    await waitFor(() =>
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/admin/craft/apps?editAppId=42"
      )
    );
  });

  it("keeps an app-associated creation open with a clear name conflict", async () => {
    const user = setupUser();
    mockCreateCustomSkillFromEditor.mockRejectedValue(
      Object.assign(new Error("This app already has a skill with that name"), {
        errorCode: "SKILL_NAME_CONFLICT",
      })
    );

    render(<SkillEditorPage externalAppId={42} externalAppName="Acme CRM" />);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Choose a different skill name")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "App “Acme CRM” already has an associated skill named “report-writer”."
      )
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Name your skill")).toHaveValue(
      "report-writer"
    );
    expect(
      screen.getByPlaceholderText("What does this skill help with?")
    ).toHaveValue("Writes reports");
    expect(
      screen.getByPlaceholderText("Write the skill instructions.")
    ).toHaveValue("Write the requested report.");
    expect(mockRouterReplace).not.toHaveBeenCalled();
    expect(mockCreateCustomSkillFromEditor).toHaveBeenCalledTimes(1);

    await user.clear(screen.getByPlaceholderText("Name your skill"));
    await user.type(
      screen.getByPlaceholderText("Name your skill"),
      "report-writer-v2"
    );
    expect(
      screen.queryByText("Choose a different skill name")
    ).not.toBeInTheDocument();
  });

  it("confirms before canceling a create page with unsaved changes", async () => {
    const user = setupUser();
    render(<SkillEditorPage />);

    expect(screen.getByText("Have an existing skill?")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Name your skill"), "draft");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByText("Discard unsaved changes?")
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("draft")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/skills");
  });

  it("sends the base version and offers a reload when it is stale", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    const stale = Object.assign(new Error("This skill changed."), {
      errorCode: "PLUGIN_VERSION_STALE",
    });
    mockPatchUserSkill.mockRejectedValue(stale);
    mockRefreshSkill.mockResolvedValue({
      ...skill,
      description: "Saved by someone else",
      current_version_id: "version-2",
    });

    render(<SkillEditorPage skillId={skill.id} />);
    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await user.clear(description);
    await user.type(description, "My edit");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(mockPatchUserSkill).toHaveBeenCalledWith(skill.id, {
      description: "My edit",
      instructions_markdown: skill.instructions_markdown,
      base_version_id: "version-1",
    });
    expect(
      await screen.findByText("This skill changed since you opened it")
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() =>
      expect(
        screen.queryByText("This skill changed since you opened it")
      ).not.toBeInTheDocument()
    );
    expect(
      screen.getByPlaceholderText("What does this skill help with?")
    ).toHaveValue("Saved by someone else");
  });

  it("keeps the base version of the form after a background refresh", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    mockPatchUserSkill.mockResolvedValue(skill);

    const { rerender } = render(<SkillEditorPage skillId={skill.id} />);
    // A focus refresh loads a version saved by someone else. The form still
    // shows version 1.
    mockUseSWR.mockReturnValue({
      data: {
        ...skill,
        description: "Saved by someone else",
        current_version_id: "version-2",
      },
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    rerender(<SkillEditorPage skillId={skill.id} />);

    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await user.clear(description);
    await user.type(description, "My edit");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(mockPatchUserSkill).toHaveBeenCalledWith(skill.id, {
      description: "My edit",
      instructions_markdown: skill.instructions_markdown,
      base_version_id: "version-1",
    });
  });

  it("takes the fields and version that a save reloads", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    mockPatchUserSkill.mockResolvedValue({
      ...skill,
      description: "Saved by someone else",
      current_version_id: "version-3",
    });
    // Another save committed after this one, before the response.
    const newer = existingSkill({
      description: "Saved by someone else",
      instructions_markdown: "Their instructions.",
      current_version_id: "version-3",
    });
    mockRefreshSkill.mockResolvedValue(newer);

    render(<SkillEditorPage skillId={skill.id} />);
    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await user.clear(description);
    await user.type(description, "My edit");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(description).toHaveValue("Saved by someone else")
    );
    expect(
      screen.getByPlaceholderText("Write the skill instructions.")
    ).toHaveValue("Their instructions.");
  });

  it("takes the fields of the version a file removal returns", async () => {
    const user = setupUser();
    const skill = existingSkill({
      files: [{ path: "notes.txt", size: 5 }],
    });
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    mockRemoveUserSkillFile.mockResolvedValue(
      existingSkill({
        description: "Saved by someone else",
        current_version_id: "version-3",
      })
    );
    mockPatchUserSkill.mockResolvedValue(skill);

    render(<SkillEditorPage skillId={skill.id} />);
    await user.click(screen.getByRole("button", { name: "Remove notes.txt" }));
    expect(mockRemoveUserSkillFile).toHaveBeenCalledWith(
      skill.id,
      "notes.txt",
      "version-1"
    );
    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await waitFor(() =>
      expect(description).toHaveValue("Saved by someone else")
    );
  });

  it("takes the fields and base version of a restored version", async () => {
    const user = setupUser();
    const skill = existingSkill({ current_version_id: "version-2" });
    mockRestoredSkill = existingSkill({
      instructions_markdown: "Restored instructions.",
      current_version_id: "version-3",
    });
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    mockPatchUserSkill.mockResolvedValue(mockRestoredSkill);

    render(<SkillEditorPage skillId={skill.id} />);
    await user.click(screen.getByRole("button", { name: "Edit sharing" }));
    await user.click(screen.getByRole("button", { name: "Restore version 1" }));

    const instructions = screen.getByPlaceholderText(
      "Write the skill instructions."
    );
    await waitFor(() =>
      expect(instructions).toHaveValue("Restored instructions.")
    );
    expect(mockRefreshSkill).toHaveBeenCalledWith(mockRestoredSkill, {
      revalidate: false,
    });
    await user.type(instructions, " More.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockPatchUserSkill).toHaveBeenCalledWith(
        skill.id,
        expect.objectContaining({ base_version_id: "version-3" })
      )
    );
  });

  it("blocks a restore while the editor has unsaved changes", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });

    render(<SkillEditorPage skillId={skill.id} />);
    await user.type(
      screen.getByPlaceholderText("Write the skill instructions."),
      " More."
    );
    await user.click(screen.getByRole("button", { name: "Edit sharing" }));

    expect(
      screen.getByRole("button", { name: "Restore version 1" })
    ).toBeDisabled();
  });

  it("keeps the old base version when the reload after a save fails", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    // The response can name a newer save than these fields.
    mockPatchUserSkill.mockResolvedValue({
      ...skill,
      description: "My edit",
      current_version_id: "version-3",
    });
    mockRefreshSkill.mockImplementation((data?: SkillEditableDetail) =>
      data === undefined
        ? Promise.reject(new Error("Network error"))
        : Promise.resolve(data)
    );
    jest.spyOn(console, "error").mockImplementation(() => {});

    render(<SkillEditorPage skillId={skill.id} />);
    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await user.clear(description);
    await user.type(description, "My edit");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockPatchUserSkill).toHaveBeenCalledTimes(1));

    await user.type(description, " again");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mockPatchUserSkill).toHaveBeenCalledTimes(2));
    expect(mockPatchUserSkill).toHaveBeenLastCalledWith(skill.id, {
      description: "My edit again",
      instructions_markdown: skill.instructions_markdown,
      base_version_id: "version-1",
    });
  });

  it("locks the fields while a file removal is pending", async () => {
    const user = setupUser();
    const skill = existingSkill({
      files: [{ path: "notes.txt", size: 5 }],
    });
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    let finishRemoval: (value: SkillEditableDetail) => void = () => {};
    mockRemoveUserSkillFile.mockReturnValue(
      new Promise<SkillEditableDetail>((resolve) => {
        finishRemoval = resolve;
      })
    );

    render(<SkillEditorPage skillId={skill.id} />);
    await user.click(screen.getByRole("button", { name: "Remove notes.txt" }));

    expect(
      screen.getByPlaceholderText("What does this skill help with?")
    ).toBeDisabled();
    finishRemoval(existingSkill({ current_version_id: "version-2" }));
    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("What does this skill help with?")
      ).toBeEnabled()
    );
  });

  it("confirms before leaving an existing skill with unsaved changes", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });

    render(<SkillEditorPage skillId={skill.id} />);
    const description = screen.getByPlaceholderText(
      "What does this skill help with?"
    );
    await user.clear(description);
    await user.type(description, "Writes detailed reports");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/skills");
    expect(mockDiscardSkillCreationDraft).not.toHaveBeenCalled();
  });

  it("returns an app-launched edit to that app on Cancel", async () => {
    const user = setupUser();
    const skill = existingSkill();
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });

    render(
      <SkillEditorPage
        skillId={skill.id}
        externalAppId={42}
        externalAppName="Acme CRM"
      />
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mockRouterReplace).toHaveBeenCalledWith(
      "/admin/craft/apps?editAppId=42"
    );
  });

  it("refreshes app associations before returning after skill deletion", async () => {
    const user = setupUser();
    const appRefresh = deferred<void>();
    const skill = existingSkill({
      external_app: {
        external_app_id: 42,
        name: "Acme CRM",
        enabled: true,
        ready: true,
      },
    });
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });
    mockMutate.mockImplementation((key: string) =>
      key === SWR_KEYS.buildExternalAppsAdmin
        ? appRefresh.promise
        : Promise.resolve()
    );

    render(
      <SkillEditorPage
        skillId={skill.id}
        externalAppId={42}
        externalAppName="Acme CRM"
      />
    );
    await user.click(screen.getByRole("button", { name: "Delete skill" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(mockDeleteUserSkill).toHaveBeenCalledWith(skill.id)
    );
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await act(async () => {
      appRefresh.resolve();
      await appRefresh.promise;
    });

    await waitFor(() =>
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/admin/craft/apps?editAppId=42"
      )
    );
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.buildExternalAppsAdmin);
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.userSkills);
  });

  it("returns app-launched skill creation to that app on Cancel", async () => {
    const user = setupUser();

    render(<SkillEditorPage externalAppId={42} externalAppName="Acme CRM" />);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mockRouterReplace).toHaveBeenCalledWith(
      "/admin/craft/apps?editAppId=42"
    );
  });

  it("keeps sharing in the header without a management section", () => {
    const skill = existingSkill({
      is_personal: false,
      public_permission: "VIEWER",
      external_app: {
        external_app_id: 42,
        name: "Acme CRM",
        enabled: true,
        ready: false,
      },
    });
    mockUseSWR.mockReturnValue({
      data: skill,
      error: undefined,
      isLoading: false,
      mutate: mockRefreshSkill,
    });

    render(<SkillEditorPage skillId={skill.id} />);

    expect(screen.queryByText("Management")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Edit sharing" })
    ).toBeInTheDocument();
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
    expect(consoleError).toHaveBeenCalledWith(
      "Failed to save skill",
      expect.any(Error)
    );
  });
});
