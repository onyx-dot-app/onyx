import { updateToolUserPreferences } from "@/lib/tools/svc";

afterEach(() => jest.restoreAllMocks());

test("saves the caller's default Chat preference through the member endpoint", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ enabled_in_chat: false }))
    );
  await expect(
    updateToolUserPreferences(20, { enabled_in_chat: false })
  ).resolves.toEqual({ enabled_in_chat: false });
  expect(fetchSpy).toHaveBeenCalledWith("/api/tool/20/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled_in_chat: false }),
  });
});

test("preserves the backend's rejected-save detail", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "Plugin is disabled" }), {
      status: 403,
    })
  );
  await expect(
    updateToolUserPreferences(20, { enabled_in_chat: true })
  ).rejects.toThrow("Plugin is disabled");
});

test.each([{}, { enabled_in_chat: "false" }, { enabled_in_chat: null }])(
  "rejects malformed preference responses: %j",
  async (body) => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(body)));
    await expect(
      updateToolUserPreferences(20, { enabled_in_chat: false })
    ).rejects.toThrow();
  }
);
