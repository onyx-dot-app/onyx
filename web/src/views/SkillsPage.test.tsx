import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import SkillsPage from "@/views/SkillsPage";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";

const mockSetSkillEnabled = jest.fn();
const mockBulkUpdateSkills = jest.fn();
const mockDeleteUserSkill = jest.fn();
const mockRefresh = jest.fn();
const mockMutate = jest.fn();
const mockToastError = jest.fn();
const mockRouterReplace = jest.fn();
const mockUseUserSkills = jest.fn();
const mockStageSkillCreationDraft = jest.fn();
const mockSearchParamsGet = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockRouterReplace }),
  usePathname: () => "/craft/v1/skills",
  useSearchParams: () => {
    const externalAppId: unknown = mockSearchParamsGet("externalAppId");
    return new URLSearchParams(
      typeof externalAppId === "string" ? { externalAppId } : {}
    );
  },
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: (...args: unknown[]) => mockUseUserSkills(...args),
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  setSkillEnabled: (...args: unknown[]) => mockSetSkillEnabled(...args),
  bulkUpdateSkills: (...args: unknown[]) => mockBulkUpdateSkills(...args),
  deleteUserSkill: (...args: unknown[]) => mockDeleteUserSkill(...args),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: {
    error: (...args: unknown[]) => mockToastError(...args),
    success: jest.fn(),
  },
}));

jest.mock("@/sections/cards/SkillCard", () => ({
  __esModule: true,
  default: ({
    item,
    onEnabledChange,
    onClick,
    onDelete,
    enablementPending,
    selection,
  }: {
    item: CustomSkill;
    onEnabledChange: (item: CustomSkill, enabled: boolean) => void;
    onClick: (item: CustomSkill) => void;
    onDelete: (item: CustomSkill) => void;
    enablementPending: boolean;
    selection?: {
      checked: boolean;
      disabled: boolean;
      onCheckedChange: (checked: boolean) => void;
    };
  }) => (
    <>
      {selection && (
        <input
          type="checkbox"
          aria-label={`Select ${item.name}`}
          checked={selection.checked}
          disabled={selection.disabled}
          onChange={(event) => selection.onCheckedChange(event.target.checked)}
        />
      )}
      <button
        type="button"
        role="switch"
        aria-label={item.name}
        aria-checked={item.enabled}
        disabled={enablementPending}
        onClick={() => onEnabledChange(item, !item.enabled)}
      >
        {item.name}
      </button>
      <button onClick={() => onClick(item)}>Preview {item.name}</button>
      <button onClick={() => onDelete(item)}>Delete {item.name}</button>
    </>
  ),
}));

jest.mock("@/lib/skills/creationDraft", () => ({
  stageSkillCreationDraft: (...args: unknown[]) =>
    mockStageSkillCreationDraft(...args),
}));

jest.mock("@/sections/modals/skills/CreateSkillModal", () => ({
  __esModule: true,
  default: ({
    open,
    onContinue,
  }: {
    open: boolean;
    onContinue: (draft: object) => void;
  }) =>
    open ? (
      <button type="button" onClick={() => onContinue({ draft: true })}>
        Continue upload
      </button>
    ) : null,
}));

jest.mock("@/sections/modals/skills/ImportSkillsFromGitHubModal", () => ({
  __esModule: true,
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? (
      <button type="button" onClick={onClose}>
        GitHub import open
      </button>
    ) : null,
}));

jest.mock("@/sections/modals/SkillPreviewModal", () => ({
  __esModule: true,
  default: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Skill instructions</div> : null,
}));

function customSkill(id: string, name: string): CustomSkill {
  return {
    source: "custom",
    id,
    name,
    description: `${name} description`,
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: false,
    can_toggle: true,
    installation_policy: "AVAILABLE",
    author_user_id: "owner-id",
    author_email: "owner@example.com",
    owner: { id: "owner-id", email: "owner@example.com" },
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    external_app: null,
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
  };
}

function builtinSkill(): SkillsList["builtins"][number] {
  return {
    ...customSkill("builtin-browser", "Browser"),
    source: "builtin",
    can_toggle: false,
    is_available: true,
    is_personal: false,
  };
}

describe("SkillsPage preference toggles", () => {
  let skillsData: SkillsList;

  function enabledCustomAt(index: number): CustomSkill {
    return {
      ...skillsData.customs[index]!,
      source: "custom",
      enabled: true,
    };
  }

  beforeEach(() => {
    skillsData = {
      builtins: [],
      customs: [
        customSkill("first-id", "first-skill"),
        customSkill("second-id", "second-skill"),
      ],
    };
    mockUseUserSkills.mockImplementation(() => ({
      data: skillsData,
      error: undefined,
      isLoading: false,
      refresh: mockRefresh,
    }));
    mockRefresh.mockImplementation(async (updater?: unknown) => {
      if (typeof updater === "function") {
        skillsData = updater(skillsData);
      }
      return skillsData;
    });
    mockMutate.mockReset();
    mockBulkUpdateSkills.mockReset();
    mockRouterReplace.mockReset();
    window.history.replaceState(null, "", "/");
    mockSearchParamsGet.mockReset();
    mockSearchParamsGet.mockReturnValue(null);
    mockStageSkillCreationDraft.mockReset();
    mockStageSkillCreationDraft.mockReturnValue("draft-id");
  });

  it("keeps shared skill previews available without sharing-management permission", async () => {
    skillsData.customs = [
      {
        ...customSkill("shared-id", "shared-skill"),
        user_permission: "VIEWER",
      },
    ];
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "Preview shared-skill" })
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Skill instructions");
  });

  it("keeps built-in skills collapsed until expanded", async () => {
    skillsData.builtins = [builtinSkill()];
    render(<SkillsPage />);
    const user = setupUser();
    const expand = screen.getByRole("button", {
      name: "Expand Built-in skills (1)",
    });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: "Preview Browser" })
    ).not.toBeInTheDocument();
    await user.click(expand);
    expect(
      screen.getByRole("button", { name: "Preview Browser" })
    ).toBeVisible();
    expect(
      screen.queryByRole("checkbox", { name: "Select Browser" })
    ).not.toBeInTheDocument();
  });

  it("expands built-in matches when searching", async () => {
    skillsData.builtins = [builtinSkill()];
    render(<SkillsPage />);
    const user = setupUser();
    await user.type(screen.getByPlaceholderText("Search skills..."), "browser");
    expect(
      await screen.findByRole("button", { name: "Preview Browser" })
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Fold Built-in skills (1)" })
    ).toHaveAttribute("aria-expanded", "true");
    await user.clear(screen.getByPlaceholderText("Search skills..."));
    expect(
      screen.getByRole("button", { name: "Expand Built-in skills (1)" })
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("does not include built-in skills on the admin page", () => {
    skillsData.builtins = [builtinSkill()];
    render(<SkillsPage admin />);
    expect(screen.queryByText("Built-in skills (1)")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Preview Browser" })
    ).not.toBeInTheDocument();
  });

  it("shows the custom empty state while keeping built-ins available", () => {
    skillsData.builtins = [builtinSkill()];
    skillsData.customs = [];
    render(<SkillsPage />);
    expect(screen.getByText("No custom skills yet")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Expand Built-in skills (1)" })
    ).toBeInTheDocument();
  });

  it("shows the admin description on the admin page", () => {
    render(<SkillsPage admin />);
    expect(
      screen.getByText("Manage skills and access across your organization.")
    ).toBeInTheDocument();
  });

  it("replaces the selection label with the count and restores it when cleared", async () => {
    render(<SkillsPage />);
    const user = setupUser();
    const row = screen.getByRole("group", { name: "Select skills" });
    expect(within(row).getByText("Select skills")).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    );
    expect(within(row).getByText("1 selected")).toBeInTheDocument();
    expect(within(row).queryByText("Select skills")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select second-skill" })
    );
    expect(within(row).getByText("2 selected")).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    expect(within(row).getByText("Select skills")).toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "Share" })
    ).not.toBeInTheDocument();
  });

  it("enables all selected skills and keeps failed skills selected", async () => {
    mockBulkUpdateSkills.mockResolvedValue({
      succeeded: ["first-id"],
      failed: [{ skill_id: "second-id", detail: "App connection required" }],
    });
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    const browseRow = screen.getByRole("group", { name: "Select skills" });
    expect(within(browseRow).getByText("2 selected")).toBeInTheDocument();
    await user.click(
      within(browseRow).getByRole("button", { name: "More actions" })
    );
    await user.click(screen.getByText("Enable for me", { exact: true }));
    await waitFor(() =>
      expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
        action: "enable",
        skill_ids: ["first-id", "second-id"],
      })
    );
    expect(
      screen.getByText("1 skill could not be updated")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select second-skill" })
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    ).not.toBeChecked();
  });

  it.each([
    { enabled: [true, true], enable: false, disable: true },
    { enabled: [false, false], enable: true, disable: false },
    { enabled: [true, false], enable: true, disable: true },
  ])(
    "offers only applicable bulk status actions for $enabled",
    async ({ enabled, enable, disable }) => {
      skillsData.customs = skillsData.customs.map((skill, index) => ({
        ...skill,
        enabled: enabled[index] ?? false,
      }));
      render(<SkillsPage />);
      const user = setupUser();
      await user.click(
        screen.getByRole("checkbox", {
          name: "Select all visible custom skills",
        })
      );
      await user.click(screen.getByRole("button", { name: "More actions" }));
      expect(
        screen.queryByText("Enable for me", { exact: true }) !== null
      ).toBe(enable);
      expect(
        screen.queryByText("Disable for me", { exact: true }) !== null
      ).toBe(disable);
      expect(screen.getByText("Delete", { exact: true })).toBeInTheDocument();
    }
  );

  it("toggles only the selected skills the user can toggle", async () => {
    skillsData.customs[1] = { ...skillsData.customs[1]!, can_toggle: false };
    mockBulkUpdateSkills.mockResolvedValue({
      succeeded: ["first-id"],
      failed: [],
    });
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Enable for me", { exact: true }));
    await waitFor(() =>
      expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
        action: "enable",
        skill_ids: ["first-id"],
      })
    );
  });

  it("holds bulk actions while a selected skill toggle is pending", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);
    await user.click(screen.getByRole("switch", { name: "first-skill" }));
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    const browseRow = screen.getByRole("group", { name: "Select skills" });
    expect(
      within(browseRow).getByRole("button", { name: "More actions" })
    ).toBeDisabled();
    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
    await waitFor(() =>
      expect(
        within(browseRow).getByRole("button", { name: "More actions" })
      ).toBeEnabled()
    );
  });

  it("locks organization access in bulk sharing when an app skill is selected", async () => {
    skillsData.customs[1] = {
      ...skillsData.customs[1]!,
      user_permission: "OWNER",
      external_app: {
        external_app_id: 7,
        name: "GitHub",
        enabled: true,
        ready: true,
      },
    };
    skillsData.customs[0] = {
      ...skillsData.customs[0]!,
      user_permission: "OWNER",
    };
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(
      screen.getByRole("button", { name: "Who can access" })
    ).toBeDisabled();
  });

  it("lists exactly the skills selected for deletion before confirming", async () => {
    const names = [
      "first-skill",
      "second-skill",
      "third-skill",
      "unselected-skill",
    ];
    skillsData.customs = names.map((name, index) => ({
      ...customSkill(`skill-${index}`, name),
      public_permission: null,
      user_permission: "OWNER",
    }));
    render(<SkillsPage />);
    const user = setupUser();
    for (const name of names.slice(0, 3)) {
      await user.click(
        screen.getByRole("checkbox", { name: `Select ${name}` })
      );
    }
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Delete", { exact: true }));
    const dialog = screen.getByRole("dialog");
    const list = within(dialog).getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    for (const name of names.slice(0, 3))
      expect(within(list).getByText(name)).toBeVisible();
    expect(
      within(list).queryByText("unselected-skill")
    ).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
  });

  it("does not let an owner who is not a manager delete a published skill", async () => {
    skillsData.customs = [
      { ...customSkill("private", "private-skill"), public_permission: null },
      customSkill("published", "published-skill"),
    ].map((skill) => ({ ...skill, user_permission: "OWNER" as const }));
    render(<SkillsPage />);
    const user = setupUser();
    for (const name of ["private-skill", "published-skill"]) {
      await user.click(
        screen.getByRole("checkbox", { name: `Select ${name}` })
      );
    }
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Delete", { exact: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("clears selection when search changes so hidden skills are not changed", async () => {
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    await user.type(screen.getByPlaceholderText("Search skills..."), "first");
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
    expect(screen.getByText("Select skills")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Enable for me" })
    ).not.toBeInTheDocument();
    expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
  });

  it("deletes an invalid skill only after confirmation and removes it from the list", async () => {
    skillsData.customs = [
      {
        ...customSkill("invalid-id", "invalid-skill"),
        is_valid: false,
        user_permission: "OWNER",
      },
    ];
    mockDeleteUserSkill.mockResolvedValue(undefined);
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "Delete invalid-skill" })
    );
    expect(mockDeleteUserSkill).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("invalid-skill");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(mockDeleteUserSkill).toHaveBeenCalledWith("invalid-id")
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("switch", { name: "invalid-skill" })
      ).not.toBeInTheDocument()
    );
  });

  it("refreshes associated apps after deletion without masking a successful delete on refresh failure", async () => {
    skillsData.customs = [
      {
        ...customSkill("associated-id", "associated-skill"),
        user_permission: "OWNER",
        external_app: {
          external_app_id: 7,
          name: "CRM",
          enabled: true,
          ready: true,
        },
      },
    ];
    mockDeleteUserSkill.mockResolvedValue(undefined);
    mockMutate.mockRejectedValue(new Error("Refresh failed"));
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<SkillsPage />);
      const user = setupUser();
      await user.click(
        screen.getByRole("button", { name: "Delete associated-skill" })
      );
      await user.click(screen.getByRole("button", { name: "Delete" }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
      );
      expect(mockMutate).toHaveBeenCalledWith("/api/build/admin/apps");
      expect(skillsData.customs).toHaveLength(0);
      expect(log).toHaveBeenCalled();
    } finally {
      log.mockRestore();
    }
  });

  it("finishes deletion while the optional app refresh is pending", async () => {
    skillsData.customs = [
      {
        ...customSkill("associated-id", "associated-skill"),
        user_permission: "OWNER",
        external_app: {
          external_app_id: 7,
          name: "CRM",
          enabled: true,
          ready: true,
        },
      },
    ];
    const refresh = deferred<void>();
    mockDeleteUserSkill.mockResolvedValue(undefined);
    mockMutate.mockReturnValue(refresh.promise);
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "Delete associated-skill" })
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    );
    expect(skillsData.customs).toHaveLength(0);
    await act(async () => refresh.resolve());
  });

  it("keeps an invalid skill and reports a failed delete", async () => {
    skillsData.customs = [
      {
        ...customSkill("invalid-id", "invalid-skill"),
        is_valid: false,
        user_permission: "OWNER",
      },
    ];
    mockDeleteUserSkill.mockRejectedValue(new Error("Delete failed"));
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "Delete invalid-skill" })
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith("Delete failed")
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(skillsData.customs).toHaveLength(1);
  });

  it("routes an uploaded skill draft to the editor without creating it", async () => {
    const user = setupUser();
    render(<SkillsPage />);

    await user.click(screen.getByRole("button", { name: "Create skill" }));
    await user.click(screen.getAllByText("Upload a skill")[0]!);
    await user.click(screen.getByRole("button", { name: "Continue upload" }));

    expect(mockStageSkillCreationDraft).toHaveBeenCalledWith({ draft: true });
    expect(mockRouterReplace).toHaveBeenCalledWith(
      "/craft/v1/skills/new?draft=draft-id"
    );
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it("offers GitHub import from the create menu", async () => {
    const user = setupUser();
    render(<SkillsPage />);

    await user.click(screen.getByRole("button", { name: "Create skill" }));
    await user.click(screen.getAllByText("Import from GitHub")[0]!);

    expect(
      screen.getByRole("button", { name: "GitHub import open" })
    ).toBeInTheDocument();
  });

  it("optimistically enables and disables only the pending skill switch", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "first-skill" });
    const secondSwitch = screen.getByRole("switch", { name: "second-skill" });
    expect(firstSwitch).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch).toBeDisabled();
    expect(secondSwitch).toHaveAttribute("aria-checked", "false");
    expect(secondSwitch).toBeEnabled();

    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
    await waitFor(() => expect(firstSwitch).toBeEnabled());
  });

  it("does not flash an unchanged same-named skill while enabling another", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    skillsData = {
      builtins: [],
      customs: [
        customSkill("first-id", "shared-name"),
        customSkill("second-id", "shared-name"),
      ],
    };
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    const [firstSwitch, secondSwitch] = screen.getAllByRole("switch", {
      name: "shared-name",
    });
    await user.click(firstSwitch!);

    expect(firstSwitch).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch).toBeDisabled();
    expect(secondSwitch).toHaveAttribute("aria-checked", "false");
    expect(secondSwitch).toBeEnabled();

    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
  });

  it("keeps simultaneous skill mutations independently optimistic and pending", async () => {
    const user = setupUser();
    const firstMutation = deferred<CustomSkill>();
    const secondMutation = deferred<CustomSkill>();
    mockSetSkillEnabled
      .mockReturnValueOnce(firstMutation.promise)
      .mockReturnValueOnce(secondMutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));
    await user.click(screen.getByRole("switch", { name: "second-skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "first-skill" });
    const secondSwitch = screen.getByRole("switch", { name: "second-skill" });
    expect(firstSwitch).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch).toBeDisabled();
    expect(secondSwitch).toHaveAttribute("aria-checked", "true");
    expect(secondSwitch).toBeDisabled();

    await act(async () => {
      firstMutation.resolve(enabledCustomAt(0));
      await firstMutation.promise;
    });
    await waitFor(() => expect(firstSwitch).toBeEnabled());
    expect(secondSwitch).toBeDisabled();

    await act(async () => {
      secondMutation.resolve(enabledCustomAt(1));
      await secondMutation.promise;
    });
  });

  it("rolls back optimistic state and shows the mutation error", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));
    const firstSwitch = screen.getByRole("switch", { name: "first-skill" });
    expect(firstSwitch).toHaveAttribute("aria-checked", "true");

    await act(async () => {
      mutation.reject(new Error("Preference update failed"));
      await mutation.promise.catch(() => undefined);
    });

    await waitFor(() => {
      expect(firstSwitch).toHaveAttribute("aria-checked", "false");
      expect(firstSwitch).toBeEnabled();
    });
    expect(mockToastError).toHaveBeenCalledWith("Preference update failed");
  });

  it("keeps a successful update when background revalidation fails", async () => {
    const user = setupUser();
    const updated = enabledCustomAt(0);
    mockSetSkillEnabled.mockResolvedValueOnce(updated);
    mockRefresh
      .mockImplementationOnce(
        async (updater: (value: SkillsList) => SkillsList) => {
          skillsData = updater(skillsData);
          return skillsData;
        }
      )
      .mockRejectedValueOnce(new Error("Refresh failed"));
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "first-skill" });
    await waitFor(() => {
      expect(firstSwitch).toHaveAttribute("aria-checked", "true");
      expect(firstSwitch).toBeEnabled();
    });
    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith(
        "first-skill was updated, but the skill list could not be refreshed."
      )
    );
    expect(mockToastError).not.toHaveBeenCalledWith(
      expect.stringContaining("Failed to enable")
    );
  });

  it("confirms before switching between skills with the same name", async () => {
    const user = setupUser();
    const first = {
      ...customSkill("first-id", "report-writer"),
      enabled: true,
    };
    const second = {
      ...customSkill("second-id", "report-writer"),
      external_app: {
        external_app_id: 42,
        name: "Acme CRM",
        enabled: true,
        ready: true,
      },
    };
    skillsData = { builtins: [], customs: [first, second] };
    mockSetSkillEnabled.mockResolvedValueOnce({ ...second, enabled: true });
    render(<SkillsPage />);

    const switches = screen.getAllByRole("switch", { name: "report-writer" });
    await user.click(switches[1]!);

    expect(mockSetSkillEnabled).not.toHaveBeenCalled();
    expect(
      screen.getByText("Switch “report-writer” skill?")
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Only one skill named “report-writer” can be enabled at a time."
      )
    ).not.toHaveLength(0);
    expect(
      screen.getByText(
        "Continuing will disable the currently enabled skill and enable this one."
      )
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockSetSkillEnabled).not.toHaveBeenCalled();

    await user.click(switches[1]!);
    await user.click(screen.getByRole("button", { name: "Switch skill" }));

    await waitFor(() =>
      expect(mockSetSkillEnabled).toHaveBeenCalledWith("second-id", true, true)
    );
    await waitFor(() => {
      expect(switches[0]).toHaveAttribute("aria-checked", "false");
      expect(switches[1]).toHaveAttribute("aria-checked", "true");
    });
    expect(
      screen.queryByText("Switch “report-writer” skill?")
    ).not.toBeInTheDocument();
  });

  it("keeps the switch confirmation open when replacement fails", async () => {
    const user = setupUser();
    const first = {
      ...customSkill("first-id", "report-writer"),
      enabled: true,
    };
    const second = customSkill("second-id", "report-writer");
    const mutation = deferred<CustomSkill>();
    skillsData = { builtins: [], customs: [first, second] };
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    await user.click(
      screen.getAllByRole("switch", { name: "report-writer" })[1]!
    );
    await user.click(screen.getByRole("button", { name: "Switch skill" }));

    expect(screen.getByRole("button", { name: "Switching..." })).toBeDisabled();
    expect(
      screen.getByText("Switch “report-writer” skill?")
    ).toBeInTheDocument();

    await act(async () => {
      mutation.reject(new Error("Replacement failed"));
      await mutation.promise.catch(() => undefined);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Switch skill" })).toBeEnabled()
    );
    expect(
      screen.getByText("Switch “report-writer” skill?")
    ).toBeInTheDocument();
    expect(mockToastError).toHaveBeenCalledWith("Replacement failed");
  });

  it("confirms a conflict reported by the server", async () => {
    const user = setupUser();
    const conflict = Object.assign(new Error("A conflict exists"), {
      errorCode: "SKILL_NAME_CONFLICT",
    });
    mockSetSkillEnabled
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce(enabledCustomAt(0));
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    expect(
      await screen.findByText("Switch “first-skill” skill?")
    ).toBeInTheDocument();
    expect(mockToastError).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Switch skill" }));
    await waitFor(() =>
      expect(mockSetSkillEnabled).toHaveBeenLastCalledWith(
        "first-id",
        true,
        true
      )
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Switch “first-skill” skill?")
      ).not.toBeInTheDocument()
    );
  });

  it("focuses the list on skills associated with a reviewed app", () => {
    mockSearchParamsGet.mockImplementation((key: string) =>
      key === "externalAppId" ? "42" : null
    );
    skillsData = {
      builtins: [],
      customs: [
        {
          ...customSkill("associated-id", "crm-workflow"),
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: true,
          },
        },
        customSkill("other-id", "other-skill"),
      ],
    };

    render(<SkillsPage />);

    expect(screen.getByText("Skills for app “Acme CRM”")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Enable every skill associated with app “Acme CRM”. The app may not work correctly without them. If another skill with the same name is enabled, enabling the app-associated skill disables the other skill for you."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "crm-workflow" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "other-skill" })
    ).not.toBeInTheDocument();
  });

  it("shows all skills when an app focus no longer resolves", () => {
    mockSearchParamsGet.mockImplementation((key: string) =>
      key === "externalAppId" ? "999" : null
    );
    skillsData = {
      builtins: [],
      customs: [
        {
          ...customSkill("associated-id", "crm-workflow"),
          external_app: {
            external_app_id: 42,
            name: "Acme CRM",
            enabled: true,
            ready: true,
          },
        },
        customSkill("other-id", "other-skill"),
      ],
    };

    render(<SkillsPage />);

    expect(screen.queryByText(/Skills for app/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "crm-workflow" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "other-skill" })
    ).toBeInTheDocument();
  });
});
