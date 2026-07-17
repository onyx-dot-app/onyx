import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SkillsPage from "@/views/SkillsPage";
import type { CustomSkill, SkillsList } from "@/lib/skills/types";

const mockSetSkillEnabled = jest.fn();
const mockRefresh = jest.fn();
const mockToastError = jest.fn();
const mockRouterPush = jest.fn();
const mockUseUserSkills = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => mockUseUserSkills(),
}));

jest.mock("@/lib/skills/api", () => ({
  setSkillEnabled: (...args: unknown[]) => mockSetSkillEnabled(...args),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: {
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("@/sections/cards/SkillCard", () => ({
  __esModule: true,
  default: ({
    item,
    onEnabledChange,
    enablementPending,
  }: {
    item: CustomSkill;
    onEnabledChange: (item: CustomSkill, enabled: boolean) => void;
    enablementPending: boolean;
  }) => (
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
  ),
}));

jest.mock("@/sections/modals/skills/CreateSkillModal", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/sections/modals/SkillPreviewModal", () => ({
  __esModule: true,
  default: () => null,
}));

function customSkill(id: string, name: string): CustomSkill {
  return {
    source: "custom",
    id,
    slug: name.toLowerCase().replaceAll(" ", "-"),
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
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
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
        customSkill("first-id", "First Skill"),
        customSkill("second-id", "Second Skill"),
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
  });

  it("optimistically enables and disables only the pending skill switch", async () => {
    const user = setupUser();
    const mutation = deferred<CustomSkill>();
    mockSetSkillEnabled.mockReturnValueOnce(mutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "First Skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "First Skill" });
    const secondSwitch = screen.getByRole("switch", { name: "Second Skill" });
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

  it("keeps simultaneous skill mutations independently optimistic and pending", async () => {
    const user = setupUser();
    const firstMutation = deferred<CustomSkill>();
    const secondMutation = deferred<CustomSkill>();
    mockSetSkillEnabled
      .mockReturnValueOnce(firstMutation.promise)
      .mockReturnValueOnce(secondMutation.promise);
    render(<SkillsPage />);

    await user.click(screen.getByRole("switch", { name: "First Skill" }));
    await user.click(screen.getByRole("switch", { name: "Second Skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "First Skill" });
    const secondSwitch = screen.getByRole("switch", { name: "Second Skill" });
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

    await user.click(screen.getByRole("switch", { name: "First Skill" }));
    const firstSwitch = screen.getByRole("switch", { name: "First Skill" });
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

    await user.click(screen.getByRole("switch", { name: "First Skill" }));

    const firstSwitch = screen.getByRole("switch", { name: "First Skill" });
    await waitFor(() => {
      expect(firstSwitch).toHaveAttribute("aria-checked", "true");
      expect(firstSwitch).toBeEnabled();
    });
    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith(
        "First Skill was updated, but the skill list could not be refreshed."
      )
    );
    expect(mockToastError).not.toHaveBeenCalledWith(
      expect.stringContaining("Failed to enable")
    );
  });
});
