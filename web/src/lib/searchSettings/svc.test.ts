import { connectEmbeddingProvider } from "@/lib/searchSettings/svc";

describe("Google embedding authentication", () => {
  afterEach(() => jest.restoreAllMocks());

  test("tests keyless credentials before saving and explicitly clears the old key", async () => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));
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
