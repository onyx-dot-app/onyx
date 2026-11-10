import {
  bulkUpdateSkills,
  listSkillVersions,
  previewSkillVersion,
  restoreSkillVersion,
  createCustomSkillFromEditor,
  isSkillNameConflict,
  resetSkillMarketplaceAccess,
  setSkillEnabled,
  SkillRequestError,
  uploadSkillBundles,
} from "@/lib/skills/api";
import { skillLimitViolationOf } from "@/lib/skills/limits";

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

  it("parses per-ZIP limit feedback and keeps ordinary upload failures", async () => {
    const limit = {
      failed_limit: "files",
      affected_user_count: 3,
      usage: null,
    };
    const failures = [
      {
        path: "limited.zip",
        name: "limited.zip",
        reason: "Server detail",
        skill_limit: limit,
      },
      { path: "bad.zip", name: "bad.zip", reason: "Invalid archive" },
      {
        path: "odd.zip",
        name: "odd.zip",
        reason: "Upload refused",
        skill_limit: { failed_limit: "folders" },
      },
    ];
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          imported: [{ skill: { id: "accepted" } }],
          not_imported: failures,
        })
      )
    );
    const result = await uploadSkillBundles([new File(["zip"], "limited.zip")]);
    expect(result.imported).toEqual([{ skill: { id: "accepted" } }]);
    expect(result.not_imported).toEqual([
      failures[0],
      { ...failures[1], skill_limit: null },
      { ...failures[2], skill_limit: null },
    ]);
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
      failed: [
        { skill_id: "skill-500", detail: "Connection lost", skill_limit: null },
      ],
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

  describe("Skill limit refusals", () => {
    const usage = {
      bytes: 520 * 1024 * 1024,
      files: 40,
      unknown_skill_count: 0,
      charged_bytes: 520 * 1024 * 1024,
      charged_files: 40,
      max_bytes: 500 * 1024 * 1024,
      max_files: 5000,
    };
    function refusal(body: unknown, status = 413) {
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify(body), { status })
      );
      return setSkillEnabled("skill-id", true).then(
        () => {
          throw new Error("expected a refusal");
        },
        (error: unknown) => error
      );
    }

    it("keeps the requester's usage and the server detail", async () => {
      const error = await refusal({
        error_code: "PAYLOAD_TOO_LARGE",
        detail: "This would put your skills at 520.0 MB",
        skill_limit: { failed_limit: "bytes", affected_user_count: 1, usage },
      });
      expect(error).toBeInstanceOf(SkillRequestError);
      expect((error as Error).message).toBe(
        "This would put your skills at 520.0 MB"
      );
      expect(skillLimitViolationOf(error)).toEqual({
        failed_limit: "bytes",
        affected_user_count: 1,
        usage,
      });
    });

    it("keeps the affected-user count when only others go over", async () => {
      const error = await refusal({
        error_code: "PAYLOAD_TOO_LARGE",
        detail: "This change would put 3 users past the limit.",
        skill_limit: {
          failed_limit: "files",
          affected_user_count: 3,
          usage: null,
        },
      });
      expect(skillLimitViolationOf(error)).toEqual({
        failed_limit: "files",
        affected_user_count: 3,
        usage: null,
      });
    });

    it("treats malformed limit data and plain 413s as ordinary errors", async () => {
      const malformed = await refusal({
        error_code: "PAYLOAD_TOO_LARGE",
        detail: "Too large",
        skill_limit: { failed_limit: "folders", affected_user_count: 1 },
      });
      expect(skillLimitViolationOf(malformed)).toBeNull();
      expect((malformed as Error).message).toBe("Too large");

      const plain = await refusal({
        error_code: "PAYLOAD_TOO_LARGE",
        detail: "Upload is too large",
      });
      expect(skillLimitViolationOf(plain)).toBeNull();
      expect((plain as Error).message).toBe("Upload is too large");

      const otherStatus = await refusal(
        {
          error_code: "PAYLOAD_TOO_LARGE",
          detail: "Bad",
          skill_limit: { failed_limit: "bytes", affected_user_count: 1, usage },
        },
        400
      );
      expect(skillLimitViolationOf(otherStatus)).toBeNull();
    });

    it("keeps per-item limits from bulk failures and falls back to detail", async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            succeeded: ["a"],
            failed: [
              {
                skill_id: "b",
                detail: "Over the limit",
                skill_limit: {
                  failed_limit: "bytes",
                  affected_user_count: 2,
                  usage: null,
                },
              },
              { skill_id: "c", detail: "Not allowed", skill_limit: null },
              { skill_id: "d", detail: "Gone" },
              {
                skill_id: "e",
                detail: "Odd",
                skill_limit: { failed_limit: "bytes" },
              },
            ],
          })
        )
      );
      const result = await bulkUpdateSkills({
        action: "enable",
        skill_ids: ["a", "b", "c", "d", "e"],
      });
      expect(result.succeeded).toEqual(["a"]);
      expect(result.failed).toEqual([
        {
          skill_id: "b",
          detail: "Over the limit",
          skill_limit: {
            failed_limit: "bytes",
            affected_user_count: 2,
            usage: null,
          },
        },
        { skill_id: "c", detail: "Not allowed", skill_limit: null },
        { skill_id: "d", detail: "Gone", skill_limit: null },
        { skill_id: "e", detail: "Odd", skill_limit: null },
      ]);
    });
  });
});
