import { connectEmbeddingProvider } from "@/lib/searchSettings/svc";

function testEmbeddingResponse(dimension: number): Response {
  return new Response(JSON.stringify({ dimension }), { status: 200 });
}

describe("Bifrost embedding provider", () => {
  afterEach(() => jest.restoreAllMocks());

  test("tests the model when the stored key is kept and returns its dimension", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async () => testEmbeddingResponse(3072));
    const dimension = await connectEmbeddingProvider({
      providerType: "bifrost",
      apiKey: null,
      apiUrl: "https://bifrost.example",
      modelName: "openai/text-embedding-3-large",
      apiVersion: null,
      deploymentName: null,
      alwaysTest: true,
    });
    expect(dimension).toBe(3072);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const testBody = JSON.parse(String(fetchSpy.mock.calls[0]?.[1]?.body));
    expect(testBody.model_name).toBe("openai/text-embedding-3-large");
    expect(testBody.api_key).toBeNull();
    const saveBody = JSON.parse(String(fetchSpy.mock.calls[1]?.[1]?.body));
    expect(saveBody.api_key_changed).toBe(false);
    expect(saveBody).not.toHaveProperty("api_key");
  });

  test("does not save the provider when the gateway rejects the model", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail:
            "The embedding provider rejected the model openai/gpt-5-mini: The model `gpt-5-mini` does not support embeddings.",
        }),
        {
          status: 400,
        }
      )
    );
    await expect(
      connectEmbeddingProvider({
        providerType: "bifrost",
        apiKey: null,
        apiUrl: "https://bifrost.example",
        modelName: "openai/gpt-5-mini",
        apiVersion: null,
        deploymentName: null,
        alwaysTest: true,
      })
    ).rejects.toThrow("does not support embeddings");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

describe("Google embedding authentication", () => {
  afterEach(() => jest.restoreAllMocks());

  test("tests keyless credentials before saving and explicitly clears the old key", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async () => testEmbeddingResponse(768));
    const vertexConfig = {
      auth_method: "workload_identity",
      project_id: "my-project",
      location: "global",
    } as const;
    await connectEmbeddingProvider({
      providerType: "google",
      apiKey: null,
      apiUrl: "",
      apiVersion: null,
      deploymentName: null,
      vertexConfig,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe(
      "/api/admin/embedding/test-embedding"
    );
    expect(fetchSpy.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(fetchSpy.mock.calls[1]?.[0]).toBe(
      "/api/admin/embedding/embedding-provider"
    );
    expect(fetchSpy.mock.calls[1]?.[1]?.method).toBe("PUT");
    const testBody = JSON.parse(String(fetchSpy.mock.calls[0]?.[1]?.body));
    const saveBody = JSON.parse(String(fetchSpy.mock.calls[1]?.[1]?.body));
    expect(testBody.vertex_config).toEqual(vertexConfig);
    expect(testBody.api_key).toBeNull();
    expect(saveBody.vertex_config).toEqual(vertexConfig);
    expect(saveBody.api_key).toBeNull();
    expect(saveBody.api_key_changed).toBe(true);
  });

  test("does not save a Workload Identity provider after authentication fails", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Permission denied" }), {
        status: 400,
      })
    );
    await expect(
      connectEmbeddingProvider({
        providerType: "google",
        apiKey: null,
        apiUrl: "",
        apiVersion: null,
        deploymentName: null,
        vertexConfig: {
          auth_method: "workload_identity",
          project_id: "my-project",
          location: "global",
        },
      })
    ).rejects.toThrow("Permission denied");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe(
      "/api/admin/embedding/test-embedding"
    );
    expect(fetchSpy.mock.calls[0]?.[1]?.method).toBe("POST");
  });
});
