import { FetchError, type ErrorResponseBody } from "@/lib/fetcher";
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
import { SWR_KEYS } from "@/lib/swr-keys";
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

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate, cache: new Map() }),
}));

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockRouterReplace }),
  usePathname: () => "/admin/skills",
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

jest.mock("@/sections/marketplaces/AddMarketplaceModal", () => ({
  __esModule: true,
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? (
      <button type="button" onClick={onClose}>
        Add marketplace open
      </button>
    ) : null,
}));

jest.mock("@/sections/marketplaces/MarketplacesTable", () => ({
  __esModule: true,
  default: () => <div>Marketplaces table</div>,
}));

let mockIsManager = false;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockIsManager,
    isScopedManager: false,
  }),
}));

jest.mock("@/sections/skills/SkillReviewRequests", () => ({
  __esModule: true,
  default: () => <div>Publish requests list</div>,
}));

jest.mock("@/sections/skills/SkillPublishingCard", () => ({
  __esModule: true,
  default: () => null,
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
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    group_summaries: [],
    required_for_user: false,
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
    member_visible: true,
    name_held_by: [],
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
    kind: "skill",
    available_count: 0,
    needed_count: 0,
    plugin: null,
    marketplace: null,
    content_locked: false,
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
    mockIsManager = false;
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
    mockStageSkillCreationDraft.mockReset();
    mockStageSkillCreationDraft.mockReturnValue("draft-id");
  });

  it("opens a custom skill on its skill page", async () => {
    skillsData.customs = [
      {
        ...customSkill("shared-id", "shared-skill"),
        user_permission: "VIEWER",
        member_visible: true,
        name_held_by: [],
      },
    ];
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(screen.getByRole("row", { name: "Open shared-skill" }));
    await waitFor(() =>
      expect(window.location.pathname).toBe("/admin/skills/shared-id")
    );
  });

  it("opens an uploaded plugin on its plugin page", async () => {
    skillsData.customs = [
      { ...customSkill("plugin-id", "review-kit"), kind: "plugin" },
    ];
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(screen.getByRole("row", { name: "Open review-kit" }));
    await waitFor(() =>
      expect(window.location.pathname).toBe("/app/customize/plugins/plugin-id")
    );
  });

  it("shows publish requests in the library to a non-admin skill manager", () => {
    mockIsManager = true;
    render(<SkillsPage />);
    expect(screen.getByText("Publish requests list")).toBeInTheDocument();
  });

  it("hides publish requests from a user who does not manage skills", () => {
    render(<SkillsPage />);
    expect(screen.queryByText("Publish requests list")).not.toBeInTheDocument();
  });

  it("does not include built-in skills on the admin page", () => {
    skillsData.builtins = [builtinSkill()];
    render(<SkillsPage />);
    expect(
      screen.queryByRole("row", { name: "Open Browser" })
    ).not.toBeInTheDocument();
  });

  it("shows the empty state with no custom skills", () => {
    skillsData.builtins = [builtinSkill()];
    skillsData.customs = [];
    render(<SkillsPage />);
    expect(screen.getByText("No custom skills yet")).toBeInTheDocument();
  });

  it("shows the admin description on the admin page", () => {
    render(<SkillsPage />);
    expect(
      screen.getByText("Manage skills and access across your organization.")
    ).toBeInTheDocument();
  });

  it("shows the selection count and bulk actions until the selection clears", async () => {
    render(<SkillsPage />);
    const user = setupUser();
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    );
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select second-skill" })
    );
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Share" })
    ).not.toBeInTheDocument();
  });

  it("enables all selected skills and keeps failed skills selected", async () => {
    mockBulkUpdateSkills.mockResolvedValue({
      succeeded: ["first-id"],
      failed: [{ skill_id: "second-id", detail: "App connection required" }],
    });
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More actions" }));
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
          name: "Select all",
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
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
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
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByRole("button", { name: "More actions" })).toBeDisabled();
    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "More actions" })).toBeEnabled()
    );
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
      member_visible: true,
      name_held_by: [],
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

  it("does not offer bulk delete when the server refuses one skill", async () => {
    skillsData.customs = [
      { ...customSkill("private", "private-skill"), public_permission: null },
      { ...customSkill("published", "published-skill"), can_delete: false },
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
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
    await user.type(screen.getByPlaceholderText("Search skills..."), "first");
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Enable for me" })
    ).not.toBeInTheDocument();
    expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
  });

  it("finds skills by owner email and by group name", async () => {
    skillsData.customs = [
      {
        ...customSkill("first-id", "first-skill"),
        owner: { id: "ana-id", email: "ana@example.com" },
      },
      {
        ...customSkill("second-id", "second-skill"),
        group_summaries: [
          {
            group_id: 3,
            group_name: "Design",
            permission: "VIEWER",
            installation_policy: null,
          },
        ],
      },
    ];
    render(<SkillsPage />);
    const user = setupUser();
    const search = screen.getByPlaceholderText("Search skills...");

    await user.type(search, "ana@");
    expect(screen.getByText("first-skill")).toBeInTheDocument();
    expect(screen.queryByText("second-skill")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "design");
    expect(screen.getByText("second-skill")).toBeInTheDocument();
    expect(screen.queryByText("first-skill")).not.toBeInTheDocument();
  });

  it("filters the list by a group of the visible group summaries", async () => {
    skillsData.customs = [
      {
        ...customSkill("first-id", "first-skill"),
        group_summaries: [
          {
            group_id: 3,
            group_name: "Design",
            permission: "VIEWER",
            installation_policy: "REQUIRED",
          },
        ],
      },
      {
        ...customSkill("second-id", "second-skill"),
        group_summaries: [
          {
            group_id: 4,
            group_name: "Ops",
            permission: null,
            installation_policy: "NOT_AVAILABLE",
          },
        ],
      },
    ];
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(screen.getByRole("checkbox", { name: "Select all" }));

    const filter = screen.getByRole("combobox", { name: "Filter by group" });
    expect(filter).toHaveValue("All groups");
    await user.click(filter);
    await user.click(screen.getByRole("option", { name: "Ops" }));

    expect(
      screen.getByRole("switch", { name: "second-skill" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "first-skill" })
    ).not.toBeInTheDocument();
    // A filter change clears the selection, as a search does.
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search skills..."), "first");
    expect(screen.getByText("No matching skills")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No skills in this group match. Try a different group or search."
      )
    ).toBeInTheDocument();
  });

  it("clears the group filter when its group leaves every summary", async () => {
    const ops = {
      group_id: 4,
      group_name: "Ops",
      permission: null,
      installation_policy: "NOT_AVAILABLE" as const,
    };
    const design = { ...ops, group_id: 3, group_name: "Design" };
    skillsData.customs = [
      { ...customSkill("first-id", "first-skill"), group_summaries: [design] },
      { ...customSkill("second-id", "second-skill"), group_summaries: [ops] },
    ];
    const { rerender } = render(<SkillsPage />);
    const user = setupUser();
    await user.click(screen.getByRole("combobox", { name: "Filter by group" }));
    await user.click(screen.getByRole("option", { name: "Ops" }));
    expect(
      screen.queryByRole("switch", { name: "first-skill" })
    ).not.toBeInTheDocument();

    skillsData = {
      ...skillsData,
      customs: [
        {
          ...customSkill("first-id", "first-skill"),
          group_summaries: [design],
        },
        { ...customSkill("second-id", "second-skill"), group_summaries: [] },
      ],
    };
    rerender(<SkillsPage />);
    skillsData = {
      ...skillsData,
      customs: [
        {
          ...customSkill("first-id", "first-skill"),
          group_summaries: [design],
        },
        { ...customSkill("second-id", "second-skill"), group_summaries: [ops] },
      ],
    };
    rerender(<SkillsPage />);

    expect(screen.getByRole("switch", { name: "first-skill" })).toBeVisible();
    expect(screen.getByRole("switch", { name: "second-skill" })).toBeVisible();
  });

  it("shows no group filter when no skill has group summaries", () => {
    render(<SkillsPage />);
    expect(
      screen.queryByRole("combobox", { name: "Filter by group" })
    ).not.toBeInTheDocument();
  });

  it("deletes an invalid skill only after confirmation and removes it from the list", async () => {
    skillsData.customs = [
      {
        ...customSkill("invalid-id", "invalid-skill"),
        is_valid: false,
        user_permission: "OWNER",
        member_visible: true,
        name_held_by: [],
      },
    ];
    mockDeleteUserSkill.mockResolvedValue(undefined);
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "More for invalid-skill" })
    );
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
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
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.chatSkills);
  });

  it("keeps an invalid skill and reports a failed delete", async () => {
    skillsData.customs = [
      {
        ...customSkill("invalid-id", "invalid-skill"),
        is_valid: false,
        user_permission: "OWNER",
        member_visible: true,
        name_held_by: [],
      },
    ];
    mockDeleteUserSkill.mockRejectedValue(new Error("Delete failed"));
    render(<SkillsPage />);
    const user = setupUser();
    await user.click(
      screen.getByRole("button", { name: "More for invalid-skill" })
    );
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
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
      "/app/customize/skills/new?draft=draft-id"
    );
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it("offers Add marketplace from the create menu and lists marketplaces", async () => {
    const user = setupUser();
    render(<SkillsPage />);

    expect(screen.getByText("Marketplaces table")).toBeInTheDocument();
    expect(screen.queryByText("Import from GitHub")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create skill" }));
    await user.click(
      screen.getByRole("menuitem", { name: /^Add marketplace/ })
    );

    expect(
      screen.getByRole("button", { name: "Add marketplace open" })
    ).toBeInTheDocument();
  });

  it("optimistically enables and disables only the pending skill switch", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    const firstSwitch = () =>
      screen.getByRole("switch", { name: "first-skill" });
    const secondSwitch = () =>
      screen.getByRole("switch", { name: "second-skill" });
    expect(firstSwitch()).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch()).toHaveAttribute("aria-disabled", "true");
    expect(secondSwitch()).toHaveAttribute("aria-checked", "false");
    expect(secondSwitch()).not.toHaveAttribute("aria-disabled", "true");

    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
    await waitFor(() =>
      expect(firstSwitch()).not.toHaveAttribute("aria-disabled", "true")
    );
    // The `@` menu in chat offers only enabled skills.
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.chatSkills);
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

    const firstSwitch = () =>
      screen.getAllByRole("switch", { name: "shared-name" })[0]!;
    const secondSwitch = () =>
      screen.getAllByRole("switch", { name: "shared-name" })[1]!;
    await user.click(firstSwitch());

    expect(firstSwitch()).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch()).toHaveAttribute("aria-disabled", "true");
    expect(secondSwitch()).toHaveAttribute("aria-checked", "false");
    expect(secondSwitch()).not.toHaveAttribute("aria-disabled", "true");

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

    const firstSwitch = () =>
      screen.getByRole("switch", { name: "first-skill" });
    const secondSwitch = () =>
      screen.getByRole("switch", { name: "second-skill" });
    expect(firstSwitch()).toHaveAttribute("aria-checked", "true");
    expect(firstSwitch()).toHaveAttribute("aria-disabled", "true");
    expect(secondSwitch()).toHaveAttribute("aria-checked", "true");
    expect(secondSwitch()).toHaveAttribute("aria-disabled", "true");

    await act(async () => {
      firstMutation.resolve(enabledCustomAt(0));
      await firstMutation.promise;
    });
    await waitFor(() =>
      expect(firstSwitch()).not.toHaveAttribute("aria-disabled", "true")
    );
    expect(secondSwitch()).toHaveAttribute("aria-disabled", "true");

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
    const firstSwitch = () =>
      screen.getByRole("switch", { name: "first-skill" });
    expect(firstSwitch()).toHaveAttribute("aria-checked", "true");

    await act(async () => {
      mutation.reject(new Error("Preference update failed"));
      await mutation.promise.catch(() => undefined);
    });

    await waitFor(() => {
      expect(firstSwitch()).toHaveAttribute("aria-checked", "false");
      expect(firstSwitch()).not.toHaveAttribute("aria-disabled", "true");
    });
    expect(mockToastError).toHaveBeenCalledWith("Preference update failed");
  });

  it("shows a user the limit when the skill limit refuses a toggle", async () => {
    const user = setupUser();
    const refused = new FetchError("Refused", 413, {
      error_code: "SKILL_LIMIT_EXCEEDED",
      detail: "Refused",
      skill_limit: {
        usage: { bytes: 520 * 1024 * 1024, files: 140 },
        max_bytes: 500 * 1024 * 1024,
        max_files: 5000,
      },
    } as ErrorResponseBody);
    mockSetSkillEnabled.mockRejectedValueOnce(refused);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith(
        "This change puts you past the skill limit of 500 MB or 5,000 files. Turn off skills you do not use, then try again."
      )
    );
  });

  it("keeps a successful update when background revalidation fails", async () => {
    const user = setupUser();
    const updated = enabledCustomAt(0);
    mockSetSkillEnabled.mockResolvedValueOnce(updated);
    mockMutate.mockRejectedValue(new Error("Refresh failed"));
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "first-skill" }));

    const firstSwitch = () =>
      screen.getByRole("switch", { name: "first-skill" });
    await waitFor(() => {
      expect(firstSwitch()).toHaveAttribute("aria-checked", "true");
      expect(firstSwitch()).not.toHaveAttribute("aria-disabled", "true");
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
    };
    skillsData = { builtins: [], customs: [first, second] };
    mockSetSkillEnabled.mockResolvedValueOnce({ ...second, enabled: true });
    render(<SkillsPage />);

    const switches = () =>
      screen.getAllByRole("switch", { name: "report-writer" });
    await user.click(switches()[1]!);

    expect(mockSetSkillEnabled).not.toHaveBeenCalled();
    expect(screen.getByText("Turn on “report-writer”?")).toBeInTheDocument();
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

    await user.click(switches()[1]!);
    await user.click(screen.getByRole("button", { name: "Switch" }));

    await waitFor(() =>
      expect(mockSetSkillEnabled).toHaveBeenCalledWith("second-id", true, true)
    );
    await waitFor(() => {
      expect(switches()[0]).toHaveAttribute("aria-checked", "false");
      expect(switches()[1]).toHaveAttribute("aria-checked", "true");
    });
    expect(
      screen.queryByText("Turn on “report-writer”?")
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
    await user.click(screen.getByRole("button", { name: "Switch" }));

    expect(screen.getByRole("button", { name: "Switching..." })).toBeDisabled();
    expect(screen.getByText("Turn on “report-writer”?")).toBeInTheDocument();

    await act(async () => {
      mutation.reject(new Error("Replacement failed"));
      await mutation.promise.catch(() => undefined);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Switch" })).toBeEnabled()
    );
    expect(screen.getByText("Turn on “report-writer”?")).toBeInTheDocument();
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
      await screen.findByText("Turn on “first-skill”?")
    ).toBeInTheDocument();
    expect(mockToastError).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() =>
      expect(mockSetSkillEnabled).toHaveBeenLastCalledWith(
        "first-id",
        true,
        true
      )
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Turn on “first-skill”?")
      ).not.toBeInTheDocument()
    );
  });
});
