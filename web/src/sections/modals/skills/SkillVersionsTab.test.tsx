import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import type { SkillVersion } from "@/lib/skills/types";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const mockFetch = jest.fn();
const mockRestoreSkillVersion = jest.fn();
const mockPublishSkill = jest.fn();
const mockToast = { success: jest.fn(), info: jest.fn(), error: jest.fn() };

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockFetch(...args),
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  restoreSkillVersion: (...args: unknown[]) => mockRestoreSkillVersion(...args),
  publishSkill: (...args: unknown[]) => mockPublishSkill(...args),
}));

let mockPublishing = "OPEN";
let mockIsManager = false;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ plugin_publishing: mockPublishing }),
}));

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockIsManager,
    isScopedManager: false,
  }),
}));

jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToast.success(...args),
    info: (...args: unknown[]) => mockToast.info(...args),
    error: (...args: unknown[]) => mockToast.error(...args),
  },
}));

function version(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    id: "version-1",
    version_number: 1,
    created_at: "2026-11-01T10:00:00Z",
    created_by_email: "owner@example.com",
    bundle_kept: true,
    is_current: false,
    review_status: "draft",
    ...overrides,
  };
}

const VERSIONS: SkillVersion[] = [
  version({ id: "version-3", version_number: 3, is_current: true }),
  version({ id: "version-2", version_number: 2 }),
  version({ id: "version-1", version_number: 1, bundle_kept: false }),
];

const SKILL = customFixture({
  id: "skill-1",
  user_permission: "OWNER",
  current_version_number: 3,
});

function renderTab(
  overrides: Partial<Parameters<typeof SkillVersionsTab>[0]> = {}
) {
  return render(
    <SkillVersionsTab
      skill={SKILL}
      canPublish
      onChanged={jest.fn()}
      {...overrides}
    />
  );
}

function staleError(): Error {
  return Object.assign(new Error("stale"), {
    errorCode: "PLUGIN_VERSION_STALE",
  });
}

describe("SkillVersionsTab", () => {
  beforeEach(() => {
    mockPublishing = "OPEN";
    mockIsManager = false;
    mockFetch.mockReset().mockImplementation(async (url: string) => {
      if (url === "/api/skills/custom/skill-1/versions") return VERSIONS;
      if (url === "/api/skills/custom/skill-1/versions/version-2") {
        return {
          version_number: 2,
          description: "Older description",
          instructions_markdown: "Older instructions.",
        };
      }
      throw new Error(`unexpected ${url}`);
    });
    mockRestoreSkillVersion.mockReset();
    mockPublishSkill.mockReset();
    Object.values(mockToast).forEach((fn) => fn.mockReset());
  });

  it("lists versions with their author and offers Restore only for kept, older versions", async () => {
    renderTab();

    expect(await screen.findByText("Version 3")).toBeVisible();
    expect(screen.getByText("Current")).toBeVisible();
    expect(screen.getAllByText("owner@example.com")).toHaveLength(3);
    expect(
      screen.getByRole("button", { name: "Restore version 2" })
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Restore version 3" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Restore version 1" })
    ).not.toBeInTheDocument();
  });

  it("restores a version from the current version and reports the new version", async () => {
    const user = setupUser();
    const onChanged = jest.fn();
    const onRestored = jest.fn();
    mockRestoreSkillVersion.mockResolvedValue({
      current_version_id: "version-4",
      current_version_number: 4,
    });
    renderTab({ onChanged, onRestored });

    await user.click(
      await screen.findByRole("button", { name: "Restore version 2" })
    );

    await waitFor(() =>
      expect(mockRestoreSkillVersion).toHaveBeenCalledWith(
        "skill-1",
        "version-2",
        "version-3"
      )
    );
    expect(mockToast.success).toHaveBeenCalledWith(
      "Restored version 2 as version 4."
    );
    expect(onRestored).toHaveBeenCalledWith({
      current_version_id: "version-4",
      current_version_number: 4,
    });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows the stale-version message when another save came first", async () => {
    const user = setupUser();
    mockRestoreSkillVersion.mockRejectedValue(staleError());
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Restore version 2" })
    );

    expect(
      await screen.findByText("This skill changed since you opened it")
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Restore version 2" })
    ).toBeDisabled();
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it("takes the restore state of a previewed version from the reloaded list", async () => {
    const user = setupUser();
    mockRestoreSkillVersion.mockRejectedValue(staleError());
    renderTab();

    await user.click(
      await screen.findByRole("row", { name: "Preview version 2" })
    );
    await user.click(
      await screen.findByRole("button", { name: "Restore version 2" })
    );
    await screen.findByText("This skill changed since you opened it");
    const pruned = VERSIONS.map((row) =>
      row.id === "version-2" ? { ...row, bundle_kept: false } : row
    );
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/api/skills/custom/skill-1/versions") return pruned;
      if (url === "/api/skills/custom/skill-1/versions/version-2") {
        return {
          version_number: 2,
          description: "Older description",
          instructions_markdown: "Older instructions.",
        };
      }
      throw new Error(`unexpected ${url}`);
    });
    await user.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() =>
      expect(
        screen.queryByText("This skill changed since you opened it")
      ).not.toBeInTheDocument()
    );
    expect(screen.getByText("Older instructions.")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Restore version 2" })
    ).not.toBeInTheDocument();
  });

  it("turns Restore off while the open editor has unsaved changes", async () => {
    renderTab({ restoreBlocked: true });

    expect(
      await screen.findByRole("button", { name: "Restore version 2" })
    ).toBeDisabled();
    expect(screen.getByText("Save your changes first")).toBeVisible();
  });

  it("opens a preview of a version from its row", async () => {
    const user = setupUser();
    renderTab();

    await user.click(
      await screen.findByRole("row", { name: "Preview version 2" })
    );

    expect(await screen.findByText("Older instructions.")).toBeVisible();
    expect(screen.getByText("Older description")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "All versions" }));
    expect(await screen.findByText("Version 3")).toBeVisible();
  });

  it("shows the current, in-review, denied and published states as badges on the version", async () => {
    mockFetch.mockResolvedValue([
      version({ id: "v4", version_number: 4, is_current: true }),
      version({ id: "v3", version_number: 3, review_status: "pending" }),
      version({ id: "v2", version_number: 2, review_status: "denied" }),
      version({ id: "v1", version_number: 1, review_status: "published" }),
    ]);
    renderTab();

    expect(await screen.findByText("Pending review")).toBeVisible();
    expect(screen.getByText("Denied")).toBeVisible();
    expect(screen.getByText("Published")).toBeVisible();
    expect(screen.getByText("Current")).toBeVisible();
    expect(screen.queryByText("Draft")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Restore version 2" })
    ).toBeVisible();
  });

  it("lets the author publish an update of unpublished changes", async () => {
    const user = setupUser();
    const onChanged = jest.fn();
    mockPublishSkill.mockResolvedValue({
      ...SKILL,
      published_version_number: 3,
    });
    renderTab({
      skill: { ...SKILL, published_version_number: 2 },
      onChanged,
    });

    expect(await screen.findByText("Unpublished changes")).toBeVisible();
    expect(screen.getByText("The organization runs version 2.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Publish update" }));

    await waitFor(() =>
      expect(mockPublishSkill).toHaveBeenCalledWith("skill-1", "version-3")
    );
    expect(mockToast.success).toHaveBeenCalledWith(
      "Published version 3 to the organization."
    );
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows the badge but no Publish update button to an editor", async () => {
    renderTab({
      skill: {
        ...SKILL,
        user_permission: "EDITOR",
        published_version_number: 2,
      },
      canPublish: false,
    });

    expect(await screen.findByText("Unpublished changes")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Publish update" })
    ).not.toBeInTheDocument();
  });

  it("explains that publishing is off instead of offering Publish update", async () => {
    mockPublishing = "OFF";
    const { unmount } = renderTab({
      skill: { ...SKILL, published_version_number: 2 },
    });

    expect(
      await screen.findByText(
        "Publishing is turned off. Ask an admin to publish this update."
      )
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Publish update" })
    ).not.toBeInTheDocument();
    unmount();

    mockIsManager = true;
    renderTab({ skill: { ...SKILL, published_version_number: 2 } });
    expect(
      await screen.findByRole("button", { name: "Publish update" })
    ).toBeVisible();
  });

  it("shows Waiting for review instead of the button while a version is pending", async () => {
    renderTab({
      skill: {
        ...SKILL,
        published_version_number: 2,
        pending_version_number: 3,
      },
    });

    expect(await screen.findByText("Waiting for review")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Publish update" })
    ).not.toBeInTheDocument();
  });

  it("offers Publish update for a version saved after the pending one", async () => {
    const user = setupUser();
    mockPublishSkill.mockResolvedValue({
      ...SKILL,
      published_version_number: 1,
      pending_version_number: 3,
    });
    renderTab({
      skill: {
        ...SKILL,
        published_version_number: 1,
        pending_version_number: 2,
      },
    });

    await user.click(
      await screen.findByRole("button", { name: "Publish update" })
    );

    expect(screen.queryByText("Waiting for review")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mockPublishSkill).toHaveBeenCalledWith("skill-1", "version-3")
    );
  });
});
