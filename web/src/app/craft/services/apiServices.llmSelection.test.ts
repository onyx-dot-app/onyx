import { createTurn } from "./apiServices";

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

    const request = jest.mocked(global.fetch).mock.calls[0]?.[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      provider: "onyx",
      provider_id: 13,
      model: "gpt-5-mini",
    });
  });
});
