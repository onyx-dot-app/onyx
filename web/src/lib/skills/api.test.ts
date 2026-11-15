import {
  bulkUpdateSkills,
  createCustomSkillFromEditor,
  importGitHubSkills,
  isSkillNameConflict,
} from "@/lib/skills/api";
import type { GitHubSkillsPreview } from "@/lib/skills/types";

describe("skills API", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "created-skill" }),
    } as Response);
    global.fetch = fetchMock;
  });

  it("sends the confirmed disabled state through editor creation", async () => {
    await createCustomSkillFromEditor({
      name: "report-writer",
      description: "Writes reports",
      instructions_markdown: "Write the report.",
      auto_enable: false,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/skills/custom/editor");
    expect(
      (fetchMock.mock.calls[0]![1]!.body as FormData).get("auto_enable")
    ).toBe("false");
    expect(
      (fetchMock.mock.calls[0]![1]!.body as FormData).get("external_app_id")
    ).toBeNull();
  });

  it("sends app context for app-launched skill creation", async () => {
    await createCustomSkillFromEditor({
      name: "acme-lookup",
      description: "Looks up Acme records",
      instructions_markdown: "Use the Acme API.",
      auto_enable: false,
      external_app_id: 17,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = fetchMock.mock.calls[0]![1]!.body as FormData;
    expect(body.get("external_app_id")).toBe("17");
    expect(body.get("auto_enable")).toBe("false");
  });

  it("sends only the pinned repository identity and selected paths when importing", async () => {
    const preview: GitHubSkillsPreview = {
      repository: "anthropics/skills",
      revision: "a".repeat(40),
      subpath: "skills",
      skills: [
        {
          path: "skills/research",
          name: "research",
          description: "Research a topic.",
          unavailable_reason: null,
        },
      ],
    };

    await importGitHubSkills(preview, ["skills/research"]);

    expect(fetchMock).toHaveBeenCalledWith("/api/skills/github/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repository: "anthropics/skills",
        revision: "a".repeat(40),
        subpath: "skills",
        paths: ["skills/research"],
      }),
    });
  });

  it("recognizes only the dedicated skill-name conflict", () => {
    expect(
      isSkillNameConflict(
        Object.assign(new Error("Conflict"), {
          errorCode: "SKILL_NAME_CONFLICT",
        })
      )
    ).toBe(true);
    expect(
      isSkillNameConflict(
        Object.assign(new Error("Different conflict"), {
          errorCode: "DUPLICATE_RESOURCE",
        })
      )
    ).toBe(false);
    expect(isSkillNameConflict(new Error("No structured code"))).toBe(false);
  });

  it("keeps successful changes when a later batch fails", async () => {
    const skillIds = Array.from(
      { length: 501 },
      (_, index) => `skill-${index}`
    );
    const succeeded = skillIds.slice(0, 500);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ succeeded, failed: [] }),
    });
    fetchMock.mockRejectedValueOnce(new Error("Connection lost"));

    const result = await bulkUpdateSkills({
      action: "share",
      skill_ids: skillIds,
      sharing: { public_permission: "VIEWER" },
    });

    expect(result).toEqual({
      succeeded,
      failed: [{ skill_id: "skill-500", detail: "Connection lost" }],
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/skills/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "share",
        skill_ids: ["skill-500"],
        sharing: { public_permission: "VIEWER" },
      }),
    });
  });
});
