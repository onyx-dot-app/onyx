import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import type { SkillVersion } from "@/lib/skills/types";

const mockFetch = jest.fn();
const mockRestoreSkillVersion = jest.fn();
const mockToast = { success: jest.fn(), info: jest.fn(), error: jest.fn() };

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockFetch(...args),
}));

jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  restoreSkillVersion: (...args: unknown[]) => mockRestoreSkillVersion(...args),
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

function staleError(): Error {
  return Object.assign(new Error("stale"), {
    errorCode: "PLUGIN_VERSION_STALE",
  });
}

describe("SkillVersionsTab", () => {
  beforeEach(() => {
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
    Object.values(mockToast).forEach((fn) => fn.mockReset());
  });

  it("lists versions with their author and offers Restore only for kept, older versions", async () => {
    render(<SkillVersionsTab skillId="skill-1" onRestored={jest.fn()} />);

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
    const onRestored = jest.fn();
    mockRestoreSkillVersion.mockResolvedValue({
      current_version_id: "version-4",
      current_version_number: 4,
    });
    render(<SkillVersionsTab skillId="skill-1" onRestored={onRestored} />);

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
  });

  it("shows the stale-version message when another save came first", async () => {
    const user = setupUser();
    mockRestoreSkillVersion.mockRejectedValue(staleError());
    render(<SkillVersionsTab skillId="skill-1" onRestored={jest.fn()} />);

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
    render(<SkillVersionsTab skillId="skill-1" onRestored={jest.fn()} />);

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
    render(
      <SkillVersionsTab
        skillId="skill-1"
        onRestored={jest.fn()}
        restoreBlocked
      />
    );

    expect(
      await screen.findByRole("button", { name: "Restore version 2" })
    ).toBeDisabled();
    expect(screen.getByText("Save your changes first")).toBeVisible();
  });

  it("opens a preview of a version from its row", async () => {
    const user = setupUser();
    render(<SkillVersionsTab skillId="skill-1" onRestored={jest.fn()} />);

    await user.click(
      await screen.findByRole("row", { name: "Preview version 2" })
    );

    expect(await screen.findByText("Older instructions.")).toBeVisible();
    expect(screen.getByText("Older description")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "All versions" }));
    expect(await screen.findByText("Version 3")).toBeVisible();
  });
});
