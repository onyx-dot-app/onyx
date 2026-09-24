import { submitGoogleSite } from "@/lib/connectors/svc";

it("retains the selected private access when linking Google Sites credentials", async () => {
  const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({ id: 7, file_paths: ["site.zip"] }),
  } as Response);
  await submitGoogleSite(
    [],
    "https://example.com",
    60,
    60,
    new Date(),
    "private",
    []
  );
  const call = fetchMock.mock.calls.find(([url]) =>
    String(url).includes("/credential/")
  );
  expect(call).toBeDefined();
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(
    expect.objectContaining({ access_type: "private" })
  );
  fetchMock.mockRestore();
});
