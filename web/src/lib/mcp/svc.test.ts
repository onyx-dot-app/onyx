import { streamMCPServerProbe } from "@/lib/mcp/svc";
describe("MCP setup requests", () => {
  afterEach(() => jest.restoreAllMocks());

  test("stream handles fragmented events and a final line without newline", async () => {
    const result = { kind: "auth_unknown", transport: null };
    const stream = [
      JSON.stringify({
        type: "progress",
        stage: "contacting_server",
        state: "success",
      }),
      JSON.stringify({
        type: "progress",
        stage: "authentication",
        state: "pending",
      }),
      JSON.stringify({ type: "result", result }),
    ].join("\n");
    const progress = jest.fn();
    jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(controller) {
            for (let index = 0; index < stream.length; index += 7)
              controller.enqueue(
                new TextEncoder().encode(stream.slice(index, index + 7))
              );
            controller.close();
          },
        })
      )
    );
    expect(
      await streamMCPServerProbe("https://mcp.example/mcp", progress)
    ).toEqual(result);
    expect(progress.mock.calls.map(([event]) => event.state)).toEqual([
      "success",
      "pending",
    ]);
  });

  test.each([
    "{broken}\n",
    '{"type":"progress","stage":"fake","state":"pending"}\n',
    '{"type":"progress","stage":"contacting_server","state":"pending"}\n',
  ])("rejects malformed or incomplete stream %s", async (body) => {
    jest.spyOn(global, "fetch").mockResolvedValueOnce(new Response(body));
    await expect(
      streamMCPServerProbe("https://mcp.example/mcp", jest.fn())
    ).rejects.toThrow();
  });
});
