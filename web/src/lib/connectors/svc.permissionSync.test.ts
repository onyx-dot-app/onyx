/** The Manage Index menu's Sync Permissions row: what the helper posts and what it hands back for each outcome. */
import { triggerPermissionSync } from "@/lib/connectors/svc";

const FALLBACK = "Failed to start the permission sync";

afterEach(() => {
  jest.restoreAllMocks();
});

function respond(ok: boolean, body: unknown): Response {
  return {
    ok,
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

test("posts to the EE sync route and resolves to null once the server takes it", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(respond(true, { success: true }));

  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBeNull();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/manage/admin/cc-pair/7/sync-permissions",
    { method: "POST" }
  );
});

test("hands back the server's detail when a sync already runs", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      respond(false, { detail: "Permissions sync task already in progress." })
    );

  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBe(
    "Permissions sync task already in progress."
  );
});

test("falls back when the request never reaches the server", async () => {
  jest.spyOn(global, "fetch").mockRejectedValue(new TypeError("offline"));

  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBe(FALLBACK);
});
