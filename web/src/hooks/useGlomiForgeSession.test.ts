import { fetchGlomiForgeSession } from "@/hooks/useGlomiForgeSession";

describe("fetchGlomiForgeSession", () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  test("loads a Glomi Forge session view", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: "session-1",
        status: "preview_ready",
        preview_url: "https://preview.example",
        latest_output: null,
        last_error: null,
      }),
    });

    await expect(fetchGlomiForgeSession("/api/glomi-forge/sessions/session-1"))
      .resolves.toEqual({
        session_id: "session-1",
        status: "preview_ready",
        preview_url: "https://preview.example",
        latest_output: null,
        last_error: null,
      });
  });

  test("throws when the API rejects the request", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    await expect(
      fetchGlomiForgeSession("/api/glomi-forge/sessions/session-1")
    ).rejects.toThrow("Failed to load Glomi Forge session: 500");
  });
});
