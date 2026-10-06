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

it("sends a private Google Sites connector's reader groups as data access", async () => {
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
    [1],
    "Site",
    [2, 3]
  );
  const call = fetchMock.mock.calls.find(([url]) =>
    String(url).includes("/credential/")
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(
    expect.objectContaining({ groups: [1], data_access: [2, 3] })
  );
  fetchMock.mockRestore();
});

it("sends manage roles as manage_access in place of groups", async () => {
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
    [1],
    "Site",
    [2],
    [{ group_id: 1, role: "operator" }]
  );
  const call = fetchMock.mock.calls.find(([url]) =>
    String(url).includes("/credential/")
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(
    expect.objectContaining({
      groups: [],
      manage_access: [{ group_id: 1, role: "operator" }],
      data_access: [2],
    })
  );
  fetchMock.mockRestore();
});
