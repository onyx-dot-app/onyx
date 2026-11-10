import {
  bulkUpdateSkills,
  listSkillVersions,
  previewSkillVersion,
  restoreSkillVersion,
  createCustomSkillFromEditor,
  isSkillNameConflict,
  resetSkillMarketplaceAccess,
} from "@/lib/skills/api";

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

  it("resets access through the dedicated route and returns saved settings", async () => {
    await expect(resetSkillMarketplaceAccess("skill-id")).resolves.toEqual({
      id: "created-skill",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/skills/custom/skill-id/reset-marketplace-access",
      { method: "POST" }
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Only company skills can follow defaults" }),
        { status: 400 }
      )
    );
    await expect(resetSkillMarketplaceAccess("skill-id")).rejects.toThrow(
      "Only company skills can follow defaults"
    );
  });

  it("reads version metadata, previews retained content and restores through dedicated routes", async () => {
    const version = {
      id: "v1",
      version_number: 1,
      created_at: "2026-11-08T12:00:00Z",
      created_by: null,
      is_current: false,
      has_bundle: true,
      marketplace_revision: null,
    };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify([version])));
    await expect(listSkillVersions("skill-id")).resolves.toEqual([version]);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/skills/custom/skill-id/versions"
    );
    const bundle = {
      name: "test",
      description: "Test",
      instructions_markdown: "Use this",
      files: [],
    };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(bundle)));
    await expect(previewSkillVersion("skill-id", "v1")).resolves.toEqual(
      bundle
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/skills/custom/skill-id/versions/v1"
    );
    await restoreSkillVersion("skill-id", "v1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/skills/custom/skill-id/versions/v1/restore",
      { method: "POST" }
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Version files are no longer retained" }),
        { status: 410 }
      )
    );
    await expect(restoreSkillVersion("skill-id", "v1")).rejects.toThrow(
      "Version files are no longer retained"
    );
  });

  it("keeps the authorization status when a history response is not JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("Unauthorized", { status: 401 })
    );
    await expect(listSkillVersions("skill-id")).rejects.toMatchObject({
      status: 401,
      message: "Request failed (401)",
    });
  });

  it("rejects malformed version metadata", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([{ id: "v1" }]))
    );
    await expect(listSkillVersions("skill-id")).rejects.toThrow();
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
