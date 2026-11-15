/** The Sync Permissions route, and the three outcomes of the POST helper it shares with cancel and release. */
import { triggerPermissionSync } from "@/lib/connectors/svc";

const FALLBACK = "Failed to start the permission sync";

afterEach(() => {
  jest.restoreAllMocks();
});

function respond(ok: boolean, body: unknown): Response {
  return { ok, json: jest.fn().mockResolvedValue(body) } as unknown as Response;
}

test("posts to the EE sync route and resolves to null once the server takes it", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(respond(true, {}));

  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBeNull();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/manage/admin/cc-pair/7/sync-permissions",
    { method: "POST" }
  );
});

test("hands back the server's detail, else the fallback when the request fails", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(respond(false, { detail: "Already in progress." }))
    .mockRejectedValueOnce(new TypeError("offline"));

  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBe(
    "Already in progress."
  );
  await expect(triggerPermissionSync(7, FALLBACK)).resolves.toBe(FALLBACK);
});
