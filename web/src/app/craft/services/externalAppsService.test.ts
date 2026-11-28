import { postConnectAppDecision } from "@/app/craft/services/externalAppsService";

describe("externalAppsService", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true });
  });

  it("posts the connect decision for the parked request", async () => {
    await postConnectAppDecision("request-1", "connected");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/build/apps/connect/request-1/decision",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "connected" }),
      }
    );
  });
});
