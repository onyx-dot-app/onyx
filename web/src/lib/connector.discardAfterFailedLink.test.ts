import { discardConnectorAfterFailedLink } from "./connector";

describe("discardConnectorAfterFailedLink", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it("deletes the connector when the server rejected the link", async () => {
    await discardConnectorAfterFailedLink(7, 400);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/manage/admin/connector/7",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("deletes the connector when the caller was out of scope", async () => {
    await discardConnectorAfterFailedLink(7, 403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([409, 500, 502])(
    "keeps the connector on status %i, the pair may exist",
    async (status) => {
      await discardConnectorAfterFailedLink(7, status);
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );

  it("does nothing on a success status", async () => {
    await discardConnectorAfterFailedLink(7, 200);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("resolves when the delete request itself fails", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    await expect(
      discardConnectorAfterFailedLink(7, 400)
    ).resolves.toBeUndefined();
  });
});
