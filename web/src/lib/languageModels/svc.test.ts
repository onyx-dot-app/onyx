import {
  deleteDefaultChatNamingModel,
  setDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  setDefaultSearchSelectionModel,
  fetchInworldModels,
  fetchModels,
} from "@/lib/languageModels/svc";

describe("Inworld model discovery", () => {
  afterEach(() => jest.restoreAllMocks());

  it("preserves routing and capability metadata through the shared dispatcher", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            name: "auto",
            display_name: "Auto",
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
            is_router: true,
          },
          {
            name: "openai/gpt-5-mini",
            display_name: "gpt-5-mini",
            max_input_tokens: 400000,
            supports_image_input: true,
            supports_reasoning: true,
            is_router: false,
          },
        ]),
        { status: 200 }
      )
    );
    const signal = new AbortController().signal;
    const result = await fetchModels(
      "inworld",
      {
        api_base: "https://api.inworld.ai/v1",
        id: 42,
      },
      signal
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/inworld/available-models",
      expect.objectContaining({
        body: JSON.stringify({
          api_base: "https://api.inworld.ai/v1",
          provider_id: 42,
        }),
        signal,
      })
    );
    expect(result.models).toEqual([
      expect.objectContaining({
        name: "auto",
        is_router: true,
        effectiveDisplayName: "Auto",
      }),
      expect.objectContaining({
        name: "openai/gpt-5-mini",
        max_input_tokens: 400000,
        supports_reasoning: true,
        supports_image_input: true,
      }),
    ]);
  });

  it("returns the backend authentication error without usable models", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid Inworld key" }), {
        status: 400,
      })
    );
    await expect(
      fetchInworldModels({
        api_base: "https://api.inworld.ai/v1",
        api_key: "invalid",
      })
    ).resolves.toEqual({ models: [], error: "Invalid Inworld key" });
  });
});

describe("chat naming model default", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("saves the selected provider and model", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await setDefaultChatNamingModel(7, "gpt-6-luna");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 7, model_name: "gpt-6-luna" }),
      }
    );
  });

  it("clears chat naming without writing another default", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await deleteDefaultChatNamingModel();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "DELETE",
      }
    );
  });

  it.each([
    ["saving", () => setDefaultChatNamingModel(7, "gpt-6-luna")],
    ["clearing", deleteDefaultChatNamingModel],
  ])("reports API errors while %s", async (_action, mutateDefault) => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Provider is unavailable" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(mutateDefault()).rejects.toThrow("Provider is unavailable");
  });
});

describe("Search selection model default", () => {
  afterEach(() => jest.restoreAllMocks());

  it("saves a provider/model independently from chat naming", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await setDefaultSearchSelectionModel(8, "search-mini");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/default-search-selection",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 8, model_name: "search-mini" }),
      }
    );
  });

  it("clears search selection without writing chat naming", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await deleteDefaultSearchSelectionModel();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/default-search-selection",
      {
        method: "DELETE",
      }
    );
  });

  it.each([
    ["saving", () => setDefaultSearchSelectionModel(8, "search-mini")],
    ["clearing", deleteDefaultSearchSelectionModel],
  ])("reports API errors while %s", async (_action, mutateDefault) => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Provider is unavailable" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      })
    );
    await expect(mutateDefault()).rejects.toThrow("Provider is unavailable");
  });
});
