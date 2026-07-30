import { createTurn, fetchMessages } from "./apiServices";

const selection = {
  providerId: 13,
  providerName: "OpenAI Compatible Test",
  provider: "openai_compatible",
  modelName: "gpt-5-mini",
};
const originalFetch = global.fetch;

describe("Craft LLM selection payloads", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("fails safely on old backends while sending the exact provider id", async () => {
    await createTurn("session-id", "hello", "request-id", undefined, selection);

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const request = jest.mocked(global.fetch).mock.calls[0]![1];
    expect(JSON.parse(String(request!.body))).toMatchObject({
      provider: "onyx",
      provider_id: 13,
      model: "gpt-5-mini",
    });
  });

  it("includes attached sandbox files in the turn payload", async () => {
    await createTurn(
      "session-id",
      "use this",
      "request-id",
      undefined,
      selection,
      [
        {
          name: "reference.png",
          path: "attachments/reference.png",
          mimeType: "image/png",
        },
      ]
    );

    const request = jest.mocked(global.fetch).mock.calls[0]![1];
    expect(JSON.parse(String(request!.body))).toMatchObject({
      attachments: [
        {
          name: "reference.png",
          path: "attachments/reference.png",
          mime_type: "image/png",
        },
      ],
    });
  });

  it("restores attached sandbox files from message metadata", async () => {
    jest.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        messages: [
          {
            id: "message-1",
            session_id: "session-id",
            turn_index: 0,
            type: "user",
            message_metadata: {
              type: "user_message",
              content: { type: "text", text: "Use this image" },
              attachments: [
                {
                  name: "reference.png",
                  path: "attachments/reference.png",
                  mime_type: "image/png",
                },
              ],
            },
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    } as Response);

    const messages = await fetchMessages("session-id");

    expect(messages[0]?.attachments).toEqual([
      {
        name: "reference.png",
        path: "attachments/reference.png",
        mimeType: "image/png",
      },
    ]);
  });
});
