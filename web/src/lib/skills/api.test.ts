import { FetchError } from "@/lib/fetcher";
import {
  bulkUpdateSkills,
  createCustomSkillFromEditor,
  deleteUserSkill,
  isSkillNameConflict,
  isSkillVersionStale,
  patchUserSkill,
  setSkillEnabled,
  skillNameConflictNames,
} from "@/lib/skills/api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("Expected the request to fail");
}

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
  });

  it("reads a name conflict and its names from the server error", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, {
        error_code: "SKILL_NAME_CONFLICT",
        detail: "Another skill named report-writer is on.",
        conflict_names: ["report-writer"],
      })
    );

    const error = await rejection(setSkillEnabled("skill-1", true));

    expect(fetchMock).toHaveBeenCalledWith("/api/skills/skill-1/enabled", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: true, replace_conflict: false }),
    });
    expect(error).toBeInstanceOf(FetchError);
    expect((error as FetchError).message).toBe(
      "Another skill named report-writer is on."
    );
    expect(isSkillNameConflict(error)).toBe(true);
    expect(isSkillVersionStale(error)).toBe(false);
    expect(skillNameConflictNames(error)).toEqual(["report-writer"]);
  });

  it("reads a stale version from the server error", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, {
        error_code: "PLUGIN_VERSION_STALE",
        detail: "A newer version was saved.",
      })
    );

    const error = await rejection(
      patchUserSkill("skill-1", { description: "New", base_version_id: "v1" })
    );

    expect(fetchMock.mock.calls[0]![0]).toBe("/api/skills/custom/skill-1");
    expect(isSkillVersionStale(error)).toBe(true);
    expect(isSkillNameConflict(error)).toBe(false);
    expect(skillNameConflictNames(error)).toEqual([]);
  });

  it("recognizes only the dedicated skill-name conflict", () => {
    expect(
      isSkillNameConflict(
        new FetchError("Different conflict", 409, {
          error_code: "DUPLICATE_RESOURCE",
        })
      )
    ).toBe(false);
    expect(isSkillNameConflict(new Error("No structured code"))).toBe(false);
  });

  it("keeps a FetchError when the error body is not JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("<html>Bad Gateway</html>", { status: 502 })
    );

    const error = await rejection(deleteUserSkill("skill-1"));

    expect(fetchMock).toHaveBeenCalledWith("/api/skills/custom/skill-1", {
      method: "DELETE",
    });
    expect(error).toBeInstanceOf(FetchError);
    expect((error as FetchError).status).toBe(502);
    expect((error as FetchError).info).toBeNull();
  });

  it("accepts an empty response to a delete", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteUserSkill("skill-1")).resolves.toBeUndefined();
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
