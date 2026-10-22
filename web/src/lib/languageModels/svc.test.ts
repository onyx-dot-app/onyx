import {
  deleteDefaultChatNamingModel,
  setDefaultChatNamingModel,
  deleteDefaultSearchSelectionModel,
  setDefaultSearchSelectionModel,
} from "@/lib/languageModels/svc";

describe("chat naming model default", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("saves the selected provider and model", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await setDefaultChatNamingModel(7, "gpt-4o-mini");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/default-chat-naming",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: 7, model_name: "gpt-4o-mini" }),
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
    ["saving", () => setDefaultChatNamingModel(7, "gpt-4o-mini")],
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
