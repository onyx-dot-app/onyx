import { discardConnectorAfterFailedLink } from "./connector";

describe("discardConnectorAfterFailedLink", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it("deletes the connector, only if still unpaired, when the server rejected the link", async () => {
    await expect(discardConnectorAfterFailedLink(7, 400)).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/manage/admin/connector/7?only_unpaired=true",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("deletes the connector when the caller was out of scope", async () => {
    await expect(discardConnectorAfterFailedLink(7, 403)).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([409, 500, 502])(
    "keeps the connector on status %i, the pair may exist",
    async (status) => {
      await expect(discardConnectorAfterFailedLink(7, status)).resolves.toBe(
        false
      );
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );

  it("does nothing on a success status", async () => {
    await expect(discardConnectorAfterFailedLink(7, 200)).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports the row kept when the server refused the delete", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Connector is paired" }),
    });
    await expect(discardConnectorAfterFailedLink(7, 400)).resolves.toBe(false);
  });

  it("reports the row kept when the delete request itself fails", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    await expect(discardConnectorAfterFailedLink(7, 400)).resolves.toBe(false);
  });
});
