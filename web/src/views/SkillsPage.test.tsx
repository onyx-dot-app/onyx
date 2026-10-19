import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SkillsPage from "@/views/SkillsPage";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";

const mockSetSkillEnabled = jest.fn();
const mockDeleteUserSkill = jest.fn();
const mockRefresh = jest.fn();
const mockMutate = jest.fn();
const mockToastError = jest.fn();
const mockRouterPush = jest.fn();
const mockUseUserSkills = jest.fn();
const mockStageSkillCreationDraft = jest.fn();
const mockSearchParamsGet = jest.fn();

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  usePathname: () => "/craft/v1/skills",
  useSearchParams: () => ({ get: mockSearchParamsGet }),
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  setSkillEnabled: (...args: unknown[]) => mockSetSkillEnabled(...args),
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
    onDelete,
    enablementPending,
  }: {
    item: CustomSkill;
    onEnabledChange: (item: CustomSkill, enabled: boolean) => void;
    onDelete: (item: CustomSkill) => void;
    enablementPending: boolean;
  }) => (
    <>
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
  default: () => null,
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
    mockRouterPush.mockReset();
    mockSearchParamsGet.mockReset();
    mockSearchParamsGet.mockReturnValue(null);
    mockStageSkillCreationDraft.mockReset();
    mockStageSkillCreationDraft.mockReturnValue("draft-id");
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
    expect(mockRouterPush).toHaveBeenCalledWith(
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
