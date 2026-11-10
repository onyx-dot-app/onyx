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
import { marketplace } from "@/sections/marketplaces/__fixtures__/marketplace";
import { Permission } from "@/lib/types";
import type { BulkSkillResult } from "@/lib/skills/api";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";

const mockListMarketplaces = jest.fn();
jest.mock("@/lib/marketplaces/api", () => ({
  ...jest.requireActual<typeof import("@/lib/marketplaces/api")>(
    "@/lib/marketplaces/api"
  ),
  listMarketplaces: () => mockListMarketplaces(),
}));

let mockPermissions: string[] = [];
let mockAdminCapabilities: string[] = [];

jest.mock("@/providers/UserProvider", () => ({
  ...jest.requireActual<typeof import("@/providers/UserProvider")>(
    "@/providers/UserProvider"
  ),
  useUser: () => ({
    isAdmin: false,
    permissions: mockPermissions,
    adminCapabilities: mockAdminCapabilities,
  }),
}));

const mockSetSkillEnabled = jest.fn();
const mockBulkUpdateSkills = jest.fn();
const mockDeleteUserSkill = jest.fn();
const mockRefresh = jest.fn();
const mockMutate = jest.fn();
const mockToastError = jest.fn();
const mockToastSuccess = jest.fn();
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
    success: (...args: unknown[]) => mockToastSuccess(...args),
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

jest.mock("@/sections/marketplaces/SyncFromGitHubDialog", () => ({
  __esModule: true,
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? (
      <button type="button" onClick={onClose}>
        GitHub sync open
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
    effective_installation_policy: "AVAILABLE",
    author_user_id: "owner-id",
    author_email: "owner@example.com",
    owner: { id: "owner-id", email: "owner@example.com" },
    ownership_vacant: false,
    marketplace: null,
    retired_at: null,
    current_version_number: null,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    group_summaries: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    external_app: null,
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
  const scrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(
    Element.prototype,
    "scrollIntoView"
  );

  afterEach(() => {
    if (scrollIntoViewDescriptor) {
      Object.defineProperty(
        Element.prototype,
        "scrollIntoView",
        scrollIntoViewDescriptor
      );
    } else {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  function enabledCustomAt(index: number): CustomSkill {
    return {
      ...skillsData.customs[index]!,
      source: "custom",
      enabled: true,
    };
  }

  beforeEach(() => {
    mockListMarketplaces.mockResolvedValue([]);
    mockPermissions = [];
    mockAdminCapabilities = [];
    Element.prototype.scrollIntoView = jest.fn();
    mockToastSuccess.mockClear();
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

  it.each([390, 1280])(
    "shows current versions in admin rows at width %s",
    (width) => {
      const originalWidth = window.innerWidth;
      skillsData.customs = [
        {
          ...customSkill("versioned", "versioned-skill"),
          current_version_number: 12,
        },
      ];
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: width,
      });
      try {
        render(<SkillsPage admin />);
        expect(screen.getByText("Version 12")).toBeVisible();
      } finally {
        Object.defineProperty(window, "innerWidth", {
          configurable: true,
          value: originalWidth,
        });
      }
    }
  );

  it.each([true, false])(
    "keeps app Skill descriptions visible when readiness is %s",
    (ready) => {
      skillsData.customs = [
        {
          ...customSkill("app-review", "review-pull-requests"),
          description: "Review pull requests before merging",
          external_app: {
            external_app_id: 7,
            name: "GitHub",
            enabled: true,
            ready,
          },
        },
      ];
      render(<SkillsPage admin />);
      expect(
        screen.getByText("Review pull requests before merging")
      ).toBeVisible();
      expect(
        screen.getByText(
          ready ? "Uses app “GitHub”" : "Connect app “GitHub” to enable"
        )
      ).toBeVisible();
    }
  );

  it("keeps mobile duplicate names and descriptions within one row", () => {
    const originalWidth = window.innerWidth;
    const name = "quarterly-customer-renewal-summary-review";
    skillsData.customs = [
      {
        ...customSkill("duplicate-a", name),
        description: "Customer success guidance",
      },
      {
        ...customSkill("duplicate-b", name),
        description: "Account manager guidance",
      },
    ];
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    });
    try {
      render(<SkillsPage admin />);
      for (const title of screen.getAllByText(name)) {
        expect(title).toHaveClass("truncate");
      }
      expect(screen.getByText("Customer success guidance")).toBeVisible();
      expect(screen.getByText("Account manager guidance")).toBeVisible();
    } finally {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: originalWidth,
      });
    }
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

  it("shows one empty-library message without a zero count", () => {
    skillsData.customs = [];
    render(<SkillsPage admin />);
    expect(screen.getByText("No custom skills yet")).toBeVisible();
    expect(screen.queryByText("0 skills")).not.toBeInTheDocument();
  });

  it("shows the admin description on the admin page", () => {
    render(<SkillsPage admin />);
    expect(
      screen.getByText("Manage skills and access across your organization.")
    ).toBeInTheDocument();
  });

  it("labels personal enablement and does not present the owner as an access grant", () => {
    skillsData.customs = [
      { ...customSkill("first", "first-skill"), user_permission: "OWNER" },
    ];
    render(<SkillsPage admin />);
    expect(
      screen.getByRole("columnheader", { name: "Enable for me" })
    ).toBeVisible();
    const row = screen.getByRole("row", { name: "first-skill" });
    expect(
      within(row).queryByText("owner@example.com")
    ).not.toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "More actions for first-skill" })
    ).toBeVisible();
  });

  it("keeps select-all in the admin header and fills a partial selection", async () => {
    render(<SkillsPage admin />);
    const user = setupUser();
    const header = screen.getByRole("columnheader", {
      name: "Select all visible custom skills",
    });
    const toolbar = screen.getByRole("group", { name: "Select skills" });
    const search = screen.getByRole("searchbox", { name: "Search skills..." });
    expect(within(toolbar).getByText("2 skills")).toBeVisible();
    expect(
      within(toolbar).queryByText("Select skills")
    ).not.toBeInTheDocument();
    expect(
      within(toolbar).queryByRole("button", { name: "Share" })
    ).not.toBeInTheDocument();
    expect(within(toolbar).queryByRole("checkbox")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    );
    const selectAll = within(header).getByRole("checkbox");
    expect(within(toolbar).getByText("1 selected")).toBeVisible();
    expect(
      within(toolbar).getByRole("button", { name: "Share" })
    ).toBeVisible();
    expect(screen.getByRole("searchbox", { name: "Search skills..." })).toBe(
      search
    );
    expect(selectAll).toBePartiallyChecked();
    await user.click(selectAll);
    expect(selectAll).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select second-skill" })
    ).toBeChecked();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(selectAll);
    expect(screen.getByRole("group", { name: "Select skills" })).toBe(toolbar);
    expect(within(toolbar).getByText("2 skills")).toBeVisible();
    expect(screen.getByRole("searchbox", { name: "Search skills..." })).toBe(
      search
    );
  });

  it("opens an admin row with the keyboard and keeps selection separate from preview", async () => {
    render(<SkillsPage admin />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const row = screen.getByRole("row", { name: "first-skill" });
    row.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toHaveTextContent("Skill instructions");
  });

  it("locks admin selection while a bulk request runs and keeps failed rows selected", async () => {
    const mutation = deferred<BulkSkillResult>();
    mockBulkUpdateSkills.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage admin />);
    const user = setupUser();
    const selectAll = screen.getByRole("checkbox", {
      name: "Select all visible custom skills",
    });
    await user.click(selectAll);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
    for (const checkbox of screen.getAllByRole("checkbox")) {
      expect(checkbox).toHaveAttribute("tabindex", "-1");
      await user.click(checkbox);
      expect(checkbox).toBeChecked();
    }
    expect(screen.getByRole("button", { name: "More actions" })).toBeDisabled();
    const controls = screen.getByRole("group", { name: "Select skills" });
    expect(within(controls).getByRole("status")).toHaveAccessibleName(
      "Loading"
    );
    expect(
      within(screen.getByRole("button", { name: "Share" })).queryByRole(
        "status"
      )
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Enable first-skill" })
    ).toHaveAttribute("aria-disabled", "true");
    await act(async () => {
      mutation.resolve({
        succeeded: ["first-id"],
        failed: [{ skill_id: "second-id", detail: "Unavailable" }],
      });
      await mutation.promise;
    });
    expect(selectAll).toBePartiallyChecked();
    expect(selectAll).toHaveAttribute("tabindex", "0");
    expect(
      screen.getByRole("checkbox", { name: "Select second-skill" })
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    ).not.toBeChecked();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(within(controls).queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Action failed for 1 skill"
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "second-skill: Unavailable"
    );
    expect(mockToastSuccess).not.toHaveBeenCalled();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
      block: "nearest",
    });
  });

  it("lists each failed skill separately", async () => {
    mockBulkUpdateSkills.mockResolvedValueOnce({
      succeeded: [],
      failed: [
        { skill_id: "first-id", detail: "Skill not found" },
        { skill_id: "second-id", detail: "Unavailable" },
      ],
    });
    render(<SkillsPage admin />);
    const user = setupUser();
    await user.click(
      screen.getByRole("checkbox", { name: "Select all visible custom skills" })
    );
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
    const alert = await screen.findByRole("alert");
    const failures = within(alert).getAllByRole("listitem");
    expect(alert).toHaveFocus();
    expect(failures).toHaveLength(2);
    expect(failures[0]).toHaveTextContent("first-skill: Skill not found");
    expect(failures[1]).toHaveTextContent("second-skill: Unavailable");
  });

  it.each([
    { top: 696, listTop: 865, scroll: true },
    { top: -279, listTop: -110, scroll: true },
    { top: 304, listTop: 473, scroll: false },
  ])(
    "reveals a tall failure heading at $top without moving a visible heading",
    async ({ top, listTop, scroll }) => {
      const rect = jest.spyOn(Element.prototype, "getBoundingClientRect");
      const height = jest.replaceProperty(window, "innerHeight", 700);
      rect.mockImplementation(function (this: Element) {
        if (this.getAttribute("role") === "alert") {
          return new DOMRect(0, top, 320, 1163);
        }
        if (this.tagName === "UL" && this.closest('[role="alert"]')) {
          return new DOMRect(0, listTop, 320, 994);
        }
        return new DOMRect();
      });
      try {
        mockBulkUpdateSkills.mockResolvedValueOnce({
          succeeded: [],
          failed: [{ skill_id: "first-id", detail: "Unavailable" }],
        });
        render(<SkillsPage admin />);
        const user = setupUser();
        await user.click(
          screen.getByRole("checkbox", { name: "Select first-skill" })
        );
        await user.click(screen.getByRole("button", { name: "More actions" }));
        await user.click(
          screen.getByRole("menuitem", { name: "Enable for me" })
        );
        expect(await screen.findByRole("alert")).toHaveFocus();
        if (scroll) {
          expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
            block: "start",
          });
        } else {
          expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
        }
      } finally {
        rect.mockRestore();
        height.restore();
      }
    }
  );

  it("announces an entirely failed bulk action and clears the error after a successful retry", async () => {
    const retry = deferred<BulkSkillResult>();
    mockBulkUpdateSkills
      .mockResolvedValueOnce({
        succeeded: [],
        failed: [{ skill_id: "first-id", detail: "Unavailable" }],
      })
      .mockReturnValueOnce(retry.promise);
    render(<SkillsPage admin />);
    const user = setupUser();
    const checkbox = screen.getByRole("checkbox", {
      name: "Select first-skill",
    });
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "first-skill: Unavailable"
    );
    expect(checkbox).toBeChecked();
    expect(mockToastSuccess).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "first-skill: Unavailable"
    );
    await act(async () => {
      retry.resolve({ succeeded: ["first-id"], failed: [] });
    });
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalledWith("1 skill updated")
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
    expect(
      screen.getByRole("searchbox", { name: "Search skills..." })
    ).toHaveFocus();
  });

  it("locks the pending admin switch and bulk actions without opening a preview", async () => {
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage admin />);
    const user = setupUser();
    const toggle = screen.getByRole("switch", { name: "Enable first-skill" });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-disabled", "true");
    expect(toggle).toHaveFocus();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", { name: "Select first-skill" })
    );
    expect(
      within(screen.getByRole("group", { name: "Select skills" })).getByRole(
        "button",
        { name: "More actions" }
      )
    ).toBeDisabled();
    await act(async () => {
      mutation.resolve(enabledCustomAt(0));
      await mutation.promise;
    });
    await waitFor(() =>
      expect(toggle).not.toHaveAttribute("aria-disabled", "true")
    );
  });

  it("labels each company installation policy without falling back to Available", () => {
    skillsData.customs = [
      {
        ...customSkill("hidden-id", "hidden-skill"),
        installation_policy: "NOT_AVAILABLE",
      },
      {
        ...customSkill("required-id", "required-skill"),
        installation_policy: "REQUIRED",
      },
    ];
    render(<SkillsPage admin />);
    const hidden = screen.getByRole("row", { name: "hidden-skill" });
    expect(within(hidden).getByText("Not available")).toBeVisible();
    expect(
      within(hidden).queryByText("Available to install")
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("row", { name: "required-skill" })).getByText(
        "Required"
      )
    ).toBeVisible();
  });

  it("shows server access and group names and keeps invalid skills manageable", async () => {
    skillsData.customs = [
      {
        ...customSkill("invalid", "invalid-skill"),
        public_permission: null,
        is_personal: false,
        is_valid: false,
        user_permission: "OWNER",
        group_summaries: [
          {
            group_id: 1,
            group_name: "Engineering",
            installation_policy: null,
            source: "direct",
          },
          {
            group_id: 2,
            group_name: "Research",
            installation_policy: "NOT_AVAILABLE",
            source: "direct",
          },
        ],
      },
    ];
    render(<SkillsPage admin />);
    const user = setupUser();
    const row = screen.getByRole("row", { name: "invalid-skill" });
    expect(within(row).getByText("Shared")).toBeVisible();
    expect(within(row).getByText("Engineering")).toBeVisible();
    expect(within(row).getByText("Research")).toBeVisible();
    expect(within(row).getByText("Not available")).toBeVisible();
    expect(within(row).getByRole("switch")).toHaveAttribute(
      "aria-disabled",
      "true"
    );
    await user.click(
      within(row).getByRole("button", {
        name: "More actions for invalid-skill",
      })
    );
    expect(screen.getByRole("menuitem", { name: "Edit skill" })).toBeVisible();
    await user.click(screen.getByRole("menuitem", { name: "Delete skill" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("invalid-skill");
    expect(mockDeleteUserSkill).not.toHaveBeenCalled();
  });

  describe("group column and filter", () => {
    const engineering = {
      group_id: 1,
      group_name: "Engineering",
      installation_policy: null,
      source: "direct",
    } as const;
    const support = {
      group_id: 2,
      group_name: "Support",
      installation_policy: "REQUIRED",
      source: "marketplace",
    } as const;

    beforeEach(() => {
      skillsData.customs = [
        {
          ...customSkill("eng-a", "eng-report"),
          group_summaries: [engineering],
        },
        {
          ...customSkill("eng-b", "eng-review"),
          group_summaries: [engineering, support],
        },
        {
          ...customSkill("support-a", "support-triage"),
          group_summaries: [support],
        },
        customSkill("ungrouped", "ungrouped-skill"),
      ];
    });

    async function chooseGroup(name: string) {
      const user = setupUser();
      await user.click(
        screen.getByRole("combobox", { name: "Filter by group" })
      );
      await user.click(screen.getByRole("option", { name: name }));
    }

    function rowNames() {
      return screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.getAttribute("aria-label"));
    }

    it("labels direct and marketplace groups with their settings", () => {
      render(<SkillsPage admin />);
      expect(
        screen.getByRole("columnheader", { name: "Groups" })
      ).toBeInTheDocument();
      const row = screen.getByRole("row", { name: "support-triage" });
      expect(within(row).getByText("Support")).toBeVisible();
      expect(within(row).getByText("Required · Marketplace")).toBeVisible();
      const engRow = screen.getByRole("row", { name: "eng-report" });
      expect(within(engRow).getByText("Engineering")).toBeVisible();
      // A direct grant without an override adds no setting beside the
      // company Installation column.
      expect(within(engRow).getAllByText("Available to install")).toHaveLength(
        1
      );
      // Empty summaries do not invent groups.
      const ungrouped = screen.getByRole("row", { name: "ungrouped-skill" });
      expect(within(ungrouped).queryByText(/Engineering|Support/)).toBeNull();
    });

    it("filters rows, count and select-all, and clears the selection", async () => {
      render(<SkillsPage admin />);
      const user = setupUser();
      const toolbar = screen.getByRole("group", { name: "Select skills" });
      expect(within(toolbar).getByText("4 skills")).toBeVisible();
      await user.click(
        screen.getByRole("checkbox", { name: "Select support-triage" })
      );
      expect(within(toolbar).getByText("1 selected")).toBeVisible();

      await chooseGroup("Engineering");
      expect(rowNames()).toEqual(["eng-report", "eng-review"]);
      expect(within(toolbar).getByText("2 skills")).toBeVisible();
      expect(within(toolbar).queryByText(/selected/)).not.toBeInTheDocument();

      await user.click(
        screen.getByRole("checkbox", {
          name: "Select all visible custom skills",
        })
      );
      expect(within(toolbar).getByText("2 selected")).toBeVisible();
      await user.click(screen.getByRole("button", { name: "More actions" }));
      await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
      await waitFor(() =>
        expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
          action: "enable",
          skill_ids: ["eng-a", "eng-b"],
        })
      );
    });

    it("clears failures and keeps the name search when the group changes", async () => {
      mockBulkUpdateSkills.mockResolvedValue({
        succeeded: [],
        failed: [{ skill_id: "eng-b", detail: "Denied" }],
      } satisfies BulkSkillResult);
      render(<SkillsPage admin />);
      const user = setupUser();
      await user.type(screen.getByPlaceholderText("Search skills..."), "eng");
      await user.click(
        screen.getByRole("checkbox", { name: "Select eng-review" })
      );
      await user.click(screen.getByRole("button", { name: "More actions" }));
      await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "eng-review: Denied"
      );
      await chooseGroup("Support");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByPlaceholderText("Search skills...")).toHaveValue(
        "eng"
      );
      expect(rowNames()).toEqual(["eng-review"]);
      expect(
        screen.getByRole("checkbox", { name: "Select eng-review" })
      ).not.toBeChecked();
    });

    it("shows a group empty state when search and group match nothing", async () => {
      render(<SkillsPage admin />);
      const user = setupUser();
      await chooseGroup("Support");
      await user.type(
        screen.getByPlaceholderText("Search skills..."),
        "eng-report"
      );
      expect(screen.getByText("No matching skills")).toBeVisible();
      expect(
        screen.getByText(
          "No skills in this group match. Try a different group or search."
        )
      ).toBeVisible();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      await chooseGroup("All groups");
      expect(rowNames()).toEqual(["eng-report"]);
    });

    it("combines the group filter with an app focus", async () => {
      mockSearchParamsGet.mockImplementation((key: string) =>
        key === "externalAppId" ? "42" : null
      );
      const app = {
        external_app_id: 42,
        name: "Acme CRM",
        enabled: true,
        ready: true,
      };
      skillsData.customs = skillsData.customs.map((skill) =>
        skill.id === "eng-b" || skill.id === "support-a"
          ? { ...skill, external_app: app }
          : skill
      );
      render(<SkillsPage admin />);
      expect(rowNames()).toEqual(["eng-review", "support-triage"]);
      await chooseGroup("Engineering");
      expect(rowNames()).toEqual(["eng-review"]);
      expect(screen.getByText("Skills for app “Acme CRM”")).toBeInTheDocument();
    });

    it("does not restore a removed group filter when the group returns", async () => {
      const original = skillsData;
      const { rerender } = render(<SkillsPage admin />);
      await chooseGroup("Engineering");
      expect(rowNames()).toEqual(["eng-report", "eng-review"]);
      skillsData = {
        ...skillsData,
        customs: skillsData.customs.map((skill) => ({
          ...skill,
          group_summaries: skill.group_summaries.filter(
            (group) => group.group_id !== engineering.group_id
          ),
        })),
      };
      rerender(<SkillsPage admin />);
      expect(rowNames()).toHaveLength(4);
      skillsData = original;
      rerender(<SkillsPage admin />);
      expect(rowNames()).toHaveLength(4);
      expect(
        screen.getByRole("combobox", { name: "Filter by group" })
      ).toHaveValue("All groups");
    });

    it("hides the filter when no visible skill has groups", () => {
      skillsData.customs = [customSkill("solo", "solo-skill")];
      render(<SkillsPage admin />);
      expect(
        screen.queryByRole("combobox", { name: "Filter by group" })
      ).not.toBeInTheDocument();
    });

    it("shows compact group labels on narrow screens", () => {
      const originalWidth = window.innerWidth;
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: 390,
      });
      try {
        render(<SkillsPage admin />);
        expect(
          screen.queryByRole("columnheader", { name: "Groups" })
        ).not.toBeInTheDocument();
        const row = screen.getByRole("row", { name: "eng-review" });
        expect(
          within(row).getByText("Groups: Engineering, Support")
        ).toHaveClass("truncate");
      } finally {
        Object.defineProperty(window, "innerWidth", {
          configurable: true,
          value: originalWidth,
        });
      }
    });
  });

  it("keeps all admin rows visible and bulk targets limited to the current search", async () => {
    skillsData.customs = Array.from({ length: 12 }, (_, i) =>
      customSkill(`id-${i}`, `skill-${i}`)
    );
    mockBulkUpdateSkills.mockResolvedValue({
      succeeded: ["id-11"],
      failed: [],
    });
    render(<SkillsPage admin />);
    const user = setupUser();
    expect(screen.getAllByRole("row")).toHaveLength(13);
    await user.type(
      screen.getByPlaceholderText("Search skills..."),
      "skill-11"
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select all visible custom skills",
      })
    );
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
    await waitFor(() =>
      expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
        action: "enable",
        skill_ids: ["id-11"],
      })
    );
  });

  it.each([false, true])(
    "keeps loading and load failures distinct from an empty admin library (error=%s)",
    (error) => {
      mockUseUserSkills.mockReturnValue({
        data: undefined,
        error: error ? new Error("offline") : undefined,
        isLoading: !error,
        refresh: mockRefresh,
      });
      render(<SkillsPage admin />);
      expect(
        screen.queryByText("No custom skills yet")
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByText("0 skills")).not.toBeInTheDocument();
      if (error)
        expect(screen.getByText("Failed to load skills")).toBeVisible();
    }
  );

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
      screen.getByRole("checkbox", {
        name: "Select all visible custom skills",
      })
    );
    expect(within(row).getByText("Select skills")).toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "Share" })
    ).not.toBeInTheDocument();
  });

  it.each([false, true])(
    "enables all selected skills and keeps failed skills selected (admin=%s)",
    async (admin) => {
      mockBulkUpdateSkills.mockResolvedValue({
        succeeded: ["first-id"],
        failed: [{ skill_id: "second-id", detail: "App connection required" }],
      });
      render(<SkillsPage admin={admin} />);
      const user = setupUser();
      await user.click(
        screen.getByRole("checkbox", {
          name: "Select all visible custom skills",
        })
      );
      const browseRow = screen.getByRole("group", { name: "Select skills" });
      expect(within(browseRow).getByText("2 selected")).toBeInTheDocument();
      await user.click(
        within(browseRow).getByRole("button", { name: "More actions" })
      );
      await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
      await waitFor(() =>
        expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
          action: "enable",
          skill_ids: ["first-id", "second-id"],
        })
      );
      expect(screen.getByText("Action failed for 1 skill")).toBeInTheDocument();
      expect(
        screen.getByRole("checkbox", { name: "Select second-skill" })
      ).toBeChecked();
      expect(
        screen.getByRole("checkbox", { name: "Select first-skill" })
      ).not.toBeChecked();
    }
  );

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

  it.each([false, true])(
    "toggles only the selected skills the user can toggle (admin=%s)",
    async (admin) => {
      skillsData.customs[1] = { ...skillsData.customs[1]!, can_toggle: false };
      mockBulkUpdateSkills.mockResolvedValue({
        succeeded: ["first-id"],
        failed: [],
      });
      render(<SkillsPage admin={admin} />);
      const user = setupUser();
      await user.click(
        screen.getByRole("checkbox", {
          name: "Select all visible custom skills",
        })
      );
      await user.click(screen.getByRole("button", { name: "More actions" }));
      await user.click(screen.getByRole("menuitem", { name: "Enable for me" }));
      await waitFor(() =>
        expect(mockBulkUpdateSkills).toHaveBeenCalledWith({
          action: "enable",
          skill_ids: ["first-id"],
        })
      );
    }
  );

  it("holds bulk actions while a selected skill toggle is pending", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);
    await user.click(screen.getByRole("switch", { name: "first-skill" }));
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select all visible custom skills",
      })
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

  it.each([
    { authority: "owner", global: false, scoped: false },
    { authority: "scoped manager", global: false, scoped: true },
    { authority: "global nonadmin", global: true, scoped: false },
  ])(
    "keeps required-skill deletion and organization sharing bounded for a $authority",
    async ({ global, scoped }) => {
      mockPermissions = global ? [Permission.MANAGE_SKILLS] : [];
      mockAdminCapabilities =
        global || scoped ? [Permission.MANAGE_SKILLS] : [];
      skillsData.customs = [
        {
          ...customSkill("required-id", "required-skill"),
          installation_policy: "REQUIRED",
          can_toggle: false,
          user_permission: global || scoped ? "EDITOR" : "OWNER",
        },
      ];
      const user = setupUser();
      render(<SkillsPage admin />);
      const row = screen.getByRole("row", { name: "required-skill" });
      await user.click(
        within(row).getByRole("button", {
          name: "More actions for required-skill",
        })
      );
      if (global) {
        expect(
          screen.getByRole("menuitem", { name: "Delete skill" })
        ).toBeEnabled();
      } else {
        expect(
          screen.queryByRole("menuitem", { name: "Delete skill" })
        ).not.toBeInTheDocument();
      }
      await user.keyboard("{Escape}");
      await user.click(within(row).getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "More actions" }));
      const bulkDelete = screen.getByRole("menuitem", { name: "Delete" });
      if (global)
        expect(bulkDelete).not.toHaveAttribute("aria-disabled", "true");
      else expect(bulkDelete).toHaveAttribute("aria-disabled", "true");
      await user.keyboard("{Escape}");
      await user.click(screen.getByRole("button", { name: "Share" }));
      const organizationAccess = screen.getByRole("button", {
        name: "Who can access",
      });
      if (global) expect(organizationAccess).toBeEnabled();
      else expect(organizationAccess).toBeDisabled();
    }
  );

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
      screen.getByRole("checkbox", {
        name: "Select all visible custom skills",
      })
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

  it.each([false, true])(
    "clears selection when search changes so hidden skills are not changed (admin=%s)",
    async (admin) => {
      render(<SkillsPage admin={admin} />);
      const user = setupUser();
      await user.click(
        screen.getByRole("checkbox", {
          name: "Select all visible custom skills",
        })
      );
      await user.type(screen.getByPlaceholderText("Search skills..."), "first");
      expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
      if (!admin) expect(screen.getByText("Select skills")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Enable for me" })
      ).not.toBeInTheDocument();
      expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
    }
  );

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

    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.click(screen.getAllByText("Upload a skill")[0]!);
    await user.click(screen.getByRole("button", { name: "Continue upload" }));

    expect(mockStageSkillCreationDraft).toHaveBeenCalledWith({ draft: true });
    expect(mockRouterReplace).toHaveBeenCalledWith(
      "/craft/v1/skills/new?draft=draft-id"
    );
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    "shows failed empty sources on the Skills page (admin=%s)",
    async (admin) => {
      skillsData = { builtins: [], customs: [] };
      mockListMarketplaces.mockResolvedValue([
        {
          ...marketplace,
          sync_requested: false,
          sync_pending: false,
          sync_status: "failed",
          last_error: "Repository unavailable",
        },
      ]);
      render(<SkillsPage admin={admin} />);
      expect(await screen.findByText("Team tools")).toBeInTheDocument();
      expect(screen.getByText("Repository unavailable")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "View details for Team tools" })
      ).toBeEnabled();
    }
  );

  it("opens a read-only preview for a company editor without management permission", async () => {
    skillsData.customs = [
      {
        ...customSkill("synced", "company-skill"),
        marketplace: {
          id: "source",
          name: "Team tools",
          personal: false,
          folder: "skills/company",
          follows_access: true,
          can_share: false,
        },
      },
    ];
    render(<SkillsPage />);
    await setupUser().click(
      screen.getByRole("button", { name: "Preview company-skill" })
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Skill instructions");
  });

  it("offers GitHub sync from the Add menu", async () => {
    const user = setupUser();
    render(<SkillsPage />);

    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.click(screen.getAllByText("Sync from GitHub")[0]!);

    expect(
      screen.getByRole("button", { name: "GitHub sync open" })
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
  it.each([
    { personal: false, manager: false },
    { personal: false, manager: true },
    { personal: true, manager: false },
  ])(
    "keeps synced row and bulk actions within authority ($personal, $manager)",
    async ({ personal, manager }) => {
      mockPermissions = manager ? [Permission.MANAGE_SKILLS] : [];
      const user = setupUser();
      skillsData = {
        builtins: [],
        customs: [
          {
            ...customSkill("synced-id", "synced-skill"),
            user_permission: "EDITOR",
            marketplace: {
              id: "source",
              name: "Team tools",
              personal,
              folder: "skills/synced-skill",
              follows_access: true,
              can_share: manager,
            },
          },
        ],
      };
      render(<SkillsPage admin />);
      expect(screen.getByText("Team tools")).toBeInTheDocument();
      expect(screen.getByText("skills/synced-skill")).toBeInTheDocument();
      await user.click(
        screen.getByRole("button", { name: "More actions for synced-skill" })
      );
      expect(
        screen.getByRole("menuitem", { name: "View content" })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("menuitem", { name: "Delete skill" })
      ).not.toBeInTheDocument();
      if (!manager)
        expect(
          screen.queryByRole("menuitem", { name: "Edit sharing" })
        ).not.toBeInTheDocument();
      await user.keyboard("{Escape}");
      await user.click(
        screen.getByRole("checkbox", { name: "Select synced-skill" })
      );
      if (!manager)
        expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
      await user.click(screen.getByRole("button", { name: "More actions" }));
      expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveAttribute(
        "aria-disabled",
        "true"
      );
      expect(mockDeleteUserSkill).not.toHaveBeenCalled();
      expect(mockBulkUpdateSkills).not.toHaveBeenCalled();
    }
  );
});
