import { restoreSession } from "./apiServices";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("restoreSession", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("returns the session on a 200", async () => {
    const session = { id: "s1" };
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(200, session));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).resolves.toEqual(
      session
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries on a transient 409 and resolves once the lock frees", async () => {
    const session = { id: "s1" };
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        jsonResponse(409, { detail: "Restore already in progress" })
      )
      .mockResolvedValueOnce(
        jsonResponse(409, { detail: "Restore already in progress" })
      )
      .mockResolvedValueOnce(jsonResponse(200, session));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).resolves.toEqual(
      session
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws after exhausting retries on persistent 409", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        jsonResponse(409, { detail: "Restore already in progress" })
      );

    await expect(
      restoreSession("s1", { retryDelayMs: 0, maxRetries: 2 })
    ).rejects.toThrow("Restore already in progress");
    // initial attempt + 2 retries
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry on a non-409 error", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(500, { detail: "boom" }));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).rejects.toThrow(
      "boom"
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
