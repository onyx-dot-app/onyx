/**
 * Integration Test: Custom LLM Provider Configuration Workflow
 *
 * Tests the complete user journey for configuring a custom LLM provider.
 * This tests the full workflow: open modal → form fill → test config → save → set as default
 */

import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CustomModal from "@/sections/modals/llmConfig/CustomModal";
import { toast } from "@/hooks/useToast";

// Mock SWR's mutate function and useSWR
const mockMutate = jest.fn();
jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    useSWRConfig: () => ({ mutate: mockMutate }),
    __esModule: true,
    default: () => ({ data: undefined, error: undefined, isLoading: false }),
  };
});

// Mock toast
jest.mock("@/hooks/useToast", () => {
  const success = jest.fn();
  const error = jest.fn();
  const toastFn = Object.assign(jest.fn(), {
    success,
    error,
    info: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
    _markLeaving: jest.fn(),
  });
  return {
    toast: toastFn,
    useToast: () => ({
      toast: toastFn,
      dismiss: toastFn.dismiss,
      clearAll: toastFn.clearAll,
    }),
  };
});

// Mock usePaidEnterpriseFeaturesEnabled
jest.mock("@/components/settings/usePaidEnterpriseFeaturesEnabled", () => ({
  usePaidEnterpriseFeaturesEnabled: () => false,
}));

describe("Custom LLM Provider Configuration Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  async function fillBasicFields(
    user: ReturnType<typeof setupUser>,
    options: {
      name: string;
      provider: string;
      modelName: string;
    }
  ) {
    const nameInput = screen.getByPlaceholderText("Display Name");
    const providerInput = screen.getByPlaceholderText("Provider Name");

    await user.type(nameInput, options.name);
    await user.type(providerInput, options.provider);

    // Fill in model name (first model row)
    const modelNameInput = screen.getByPlaceholderText("Model name");
    await user.type(modelNameInput, options.modelName);
  }

  test("creates a new custom LLM provider successfully", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider?is_creation=true
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 1,
        name: "My Custom Provider",
        provider: "openai",
      }),
    } as Response);

    render(<CustomModal open={true} onOpenChange={() => {}} />);

    await fillBasicFields(user, {
      name: "My Custom Provider",
      provider: "openai",
      modelName: "gpt-4",
    });

    // Submit the form
    const submitButton = screen.getByRole("button", { name: /connect/i });
    await user.click(submitButton);

    // Verify test API was called first
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/test",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    // Verify create API was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/provider?is_creation=true",
        expect.objectContaining({
          method: "PUT",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    // Verify success toast
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        "Provider enabled successfully!"
      );
    });

    // Verify SWR cache was invalidated
    expect(mockMutate).toHaveBeenCalledWith("/api/admin/llm/provider");
    expect(mockMutate).toHaveBeenCalledWith("/api/llm/provider");

    const personaProvidersMutateCall = mockMutate.mock.calls.find(
      ([key]) => typeof key === "function"
    );
    expect(personaProvidersMutateCall).toBeDefined();

    const personaProviderFilter = personaProvidersMutateCall?.[0] as (
      key: unknown
    ) => boolean;
    expect(personaProviderFilter("/api/llm/persona/42/providers")).toBe(true);
    expect(personaProviderFilter("/api/llm/provider")).toBe(false);
  });

  test("shows error when test configuration fails", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test (failure)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Invalid API key" }),
    } as Response);

    render(<CustomModal open={true} onOpenChange={() => {}} />);

    await fillBasicFields(user, {
      name: "Bad Provider",
      provider: "openai",
      modelName: "gpt-4",
    });

    // Submit the form
    const submitButton = screen.getByRole("button", { name: /connect/i });
    await user.click(submitButton);

    // Verify test API was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/test",
        expect.objectContaining({
          method: "POST",
        })
      );
    });

    // Verify error toast is displayed with the API error message
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Invalid API key");
    });

    // Verify create API was NOT called
    expect(
      fetchSpy.mock.calls.find((call) =>
        call[0].includes("/api/admin/llm/provider")
      )
    ).toBeUndefined();
  });

  test("updates an existing LLM provider", async () => {
    const user = setupUser();

    const existingProvider = {
      id: 1,
      name: "Existing Provider",
      provider: "anthropic",
      api_key: "old-key",
      api_base: "",
      api_version: "",
      model_configurations: [
        {
          name: "claude-3-opus",
          display_name: "",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: false,
        },
      ],
      custom_config: {},
      is_public: true,
      is_auto_mode: false,
      groups: [],
      personas: [],
      deployment_name: null,
    };

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider (update, no is_creation param)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ...existingProvider }),
    } as Response);

    render(
      <CustomModal
        existingLlmProvider={existingProvider}
        open={true}
        onOpenChange={() => {}}
      />
    );

    // Make a change to dirty the form (Update is disabled until dirty)
    const modelInputs = screen.getAllByPlaceholderText("Model name");
    await user.type(modelInputs[0]!, "-updated");

    // Submit — button says "Update" for existing providers
    const submitButton = screen.getByRole("button", { name: /update/i });
    await user.click(submitButton);

    // Verify test was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/test",
        expect.any(Object)
      );
    });

    // Verify update API was called (without is_creation param)
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/provider",
        expect.objectContaining({
          method: "PUT",
        })
      );
    });

    // Verify success message says "updated"
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        "Provider updated successfully!"
      );
    });
  });

  test("preserves additional models when updating a provider", async () => {
    const user = setupUser();

    const existingProvider = {
      id: 7,
      name: "ArcAI",
      provider: "openai",
      api_key: "old-key",
      api_base: "https://example-openai-compatible.local/v1",
      api_version: "",
      model_configurations: [
        {
          name: "gpt-oss-20b-bw-failover",
          display_name: "",
          is_visible: true,
          max_input_tokens: null,
          supports_image_input: false,
          supports_reasoning: false,
        },
      ],
      custom_config: {},
      is_public: true,
      is_auto_mode: false,
      groups: [],
      personas: [],
      deployment_name: null,
    };

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...existingProvider,
        model_configurations: [
          ...existingProvider.model_configurations,
          {
            name: "nemotron",
            display_name: "",
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
          },
        ],
      }),
    } as Response);

    render(
      <CustomModal
        existingLlmProvider={existingProvider}
        open={true}
        onOpenChange={() => {}}
      />
    );

    // Add a new model
    const addModelButton = screen.getByRole("button", { name: /add model/i });
    await user.click(addModelButton);

    // Fill in second model name
    const modelInputs = screen.getAllByPlaceholderText("Model name");
    await user.type(modelInputs[1]!, "nemotron");

    const submitButton = screen.getByRole("button", { name: /update/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/provider",
        expect.objectContaining({
          method: "PUT",
        })
      );
    });

    const updateCall = fetchSpy.mock.calls.find(
      (call) =>
        call[0] === "/api/admin/llm/provider" &&
        call[1]?.method?.toUpperCase() === "PUT"
    );
    expect(updateCall).toBeDefined();

    const requestBody = JSON.parse(updateCall![1].body as string);
    expect(requestBody.model_configurations).toHaveLength(2);
    expect(requestBody.model_configurations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "gpt-oss-20b-bw-failover" }),
        expect.objectContaining({ name: "nemotron" }),
      ])
    );
  });

  test("sets provider as default when shouldMarkAsDefault is true", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider?is_creation=true
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 5,
        name: "New Default Provider",
        provider: "openai",
      }),
    } as Response);

    // Mock POST /api/admin/llm/default
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(
      <CustomModal
        shouldMarkAsDefault={true}
        open={true}
        onOpenChange={() => {}}
      />
    );

    await fillBasicFields(user, {
      name: "New Default Provider",
      provider: "openai",
      modelName: "gpt-4",
    });

    // Submit
    const submitButton = screen.getByRole("button", { name: /connect/i });
    await user.click(submitButton);

    // Verify set as default API was called with correct endpoint and body
    await waitFor(() => {
      const defaultCall = fetchSpy.mock.calls.find(
        ([url]) => url === "/api/admin/llm/default"
      );
      expect(defaultCall).toBeDefined();

      const [, options] = defaultCall!;
      expect(options.method).toBe("POST");
      expect(options.headers).toEqual({ "Content-Type": "application/json" });

      const body = JSON.parse(options.body);
      expect(body.provider_id).toBe(5);
      expect(body).toHaveProperty("model_name");
    });
  });

  test("shows error when provider creation fails", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider?is_creation=true (failure)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Database error" }),
    } as Response);

    render(<CustomModal open={true} onOpenChange={() => {}} />);

    await fillBasicFields(user, {
      name: "Test Provider",
      provider: "openai",
      modelName: "gpt-4",
    });

    // Submit
    const submitButton = screen.getByRole("button", { name: /connect/i });
    await user.click(submitButton);

    // Verify error toast
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to enable provider: Database error"
      );
    });
  });

  test("adds custom configuration key-value pairs", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock PUT /api/admin/llm/provider?is_creation=true
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 1, name: "Provider with Custom Config" }),
    } as Response);

    render(<CustomModal open={true} onOpenChange={() => {}} />);

    // Fill basic fields
    const nameInput = screen.getByPlaceholderText("Display Name");
    await user.type(nameInput, "Cloudflare Provider");

    const providerInput = screen.getByPlaceholderText("Provider Name");
    await user.type(providerInput, "cloudflare");

    // Click "Add Line" button for custom config (aria-label from KeyValueInput)
    const addLineButton = screen.getByRole("button", {
      name: /add key and value pair/i,
    });
    await user.click(addLineButton);

    // Fill in custom config key-value pair
    const keyInputs = screen.getAllByPlaceholderText(
      "e.g. api_base, api_version, api_key"
    );
    const valueInputs = screen.getAllByRole("textbox", { name: /Value \d+/ });

    await user.type(keyInputs[0]!, "CLOUDFLARE_ACCOUNT_ID");
    await user.type(valueInputs[0]!, "my-account-id-123");

    // Fill in model name
    const modelNameInput = screen.getByPlaceholderText("Model name");
    await user.type(modelNameInput, "@cf/meta/llama-2-7b-chat-int8");

    // Submit
    const submitButton = screen.getByRole("button", { name: /connect/i });
    await user.click(submitButton);

    // Verify the custom config was included in the request
    await waitFor(() => {
      const createCall = fetchSpy.mock.calls.find((call) =>
        call[0].includes("/api/admin/llm/provider")
      );
      expect(createCall).toBeDefined();

      const requestBody = JSON.parse(createCall![1].body);
      expect(requestBody.custom_config).toEqual({
        CLOUDFLARE_ACCOUNT_ID: "my-account-id-123",
      });
    });
  });
});
