/**
 * Integration Test: Custom LLM Provider Configuration Workflow
 *
 * Tests the complete user journey for configuring a custom LLM provider.
 * This tests the full workflow: form fill → test config → save → set as default
 */
import React from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";

// Mock SWR's mutate function
const mockMutate = jest.fn();
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

// Mock usePaidEnterpriseFeaturesEnabled
jest.mock("@/components/settings/usePaidEnterpriseFeaturesEnabled", () => ({
  usePaidEnterpriseFeaturesEnabled: () => false,
}));

describe("Custom LLM Provider Configuration Workflow", () => {
  let fetchSpy: jest.SpyInstance;
  const mockOnClose = jest.fn();
  const mockSetPopup = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

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
        api_key: "test-key",
        default_model_name: "gpt-4",
      }),
    } as Response);

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        setPopup={mockSetPopup}
      />
    );

    // Fill in the form
    const nameInput = screen.getByPlaceholderText(/display name/i);
    const providerInput = screen.getByPlaceholderText(
      /name of the custom provider/i
    );
    const apiKeyInput = screen.getByPlaceholderText(/api key/i);

    await user.type(nameInput, "My Custom Provider");
    await user.type(providerInput, "openai");
    await user.type(apiKeyInput, "test-key-123");

    // Fill in model configuration (use placeholder to find input)
    const modelNameInput = screen.getByPlaceholderText(/model-name-1/i);
    await user.type(modelNameInput, "gpt-4");

    // Set default model (there are 2 inputs with this placeholder - default and fast)
    // We want the first one (Default Model)
    const defaultModelInputs = screen.getAllByPlaceholderText(/e\.g\. gpt-4/i);
    await user.type(defaultModelInputs[0], "gpt-4");

    // Submit the form
    const submitButton = screen.getByRole("button", { name: /enable/i });
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

    // Verify success popup
    await waitFor(() => {
      expect(mockSetPopup).toHaveBeenCalledWith({
        type: "success",
        message: "Provider enabled successfully!",
      });
    });

    // Verify onClose was called
    expect(mockOnClose).toHaveBeenCalled();

    // Verify SWR cache was invalidated
    expect(mockMutate).toHaveBeenCalledWith("/api/admin/llm/provider");
  });

  test("shows error when test configuration fails", async () => {
    const user = setupUser();

    // Mock POST /api/admin/llm/test (failure)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Invalid API key" }),
    } as Response);

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        setPopup={mockSetPopup}
      />
    );

    // Fill in the form with invalid credentials
    const nameInput = screen.getByPlaceholderText(/display name/i);
    const providerInput = screen.getByPlaceholderText(
      /name of the custom provider/i
    );
    const apiKeyInput = screen.getByPlaceholderText(/api key/i);

    await user.type(nameInput, "Bad Provider");
    await user.type(providerInput, "openai");
    await user.type(apiKeyInput, "invalid-key");

    // Fill in model configuration
    const modelNameInput = screen.getByPlaceholderText(/model-name-1/i);
    await user.type(modelNameInput, "gpt-4");

    // Set default model (there are 2 inputs with this placeholder - default and fast)
    const defaultModelInputs = screen.getAllByPlaceholderText(/e\.g\. gpt-4/i);
    await user.type(defaultModelInputs[0], "gpt-4");

    // Submit the form
    const submitButton = screen.getByRole("button", { name: /enable/i });
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

    // Verify error is displayed (form should NOT proceed to create)
    await waitFor(() => {
      expect(screen.getByText(/invalid api key/i)).toBeInTheDocument();
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
      default_model_name: "claude-3-opus",
      fast_default_model_name: null,
      model_configurations: [
        { name: "claude-3-opus", is_visible: true, max_input_tokens: null },
      ],
      custom_config: {},
      is_public: true,
      groups: [],
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
      json: async () => ({ ...existingProvider, api_key: "new-key" }),
    } as Response);

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        existingLlmProvider={existingProvider}
        setPopup={mockSetPopup}
      />
    );

    // Update the API key
    const apiKeyInput = screen.getByPlaceholderText(/api key/i);
    await user.clear(apiKeyInput);
    await user.type(apiKeyInput, "new-key-456");

    // Submit
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
      expect(mockSetPopup).toHaveBeenCalledWith({
        type: "success",
        message: "Provider updated successfully!",
      });
    });
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

    // Mock POST /api/admin/llm/provider/5/default
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        setPopup={mockSetPopup}
        shouldMarkAsDefault={true}
      />
    );

    // Fill form
    const nameInput = screen.getByPlaceholderText(/display name/i);
    await user.type(nameInput, "New Default Provider");

    const providerInput = screen.getByPlaceholderText(
      /name of the custom provider/i
    );
    await user.type(providerInput, "openai");

    // Fill in model configuration
    const modelNameInput = screen.getByPlaceholderText(/model-name-1/i);
    await user.type(modelNameInput, "gpt-4");

    // Set default model (there are 2 inputs with this placeholder - default and fast)
    const defaultModelInputs = screen.getAllByPlaceholderText(/e\.g\. gpt-4/i);
    await user.type(defaultModelInputs[0], "gpt-4");

    // Submit
    const submitButton = screen.getByRole("button", { name: /enable/i });
    await user.click(submitButton);

    // Verify set as default API was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/llm/provider/5/default",
        expect.objectContaining({
          method: "POST",
        })
      );
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

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        setPopup={mockSetPopup}
      />
    );

    // Fill form
    const nameInput = screen.getByPlaceholderText(/display name/i);
    await user.type(nameInput, "Test Provider");

    const providerInput = screen.getByPlaceholderText(
      /name of the custom provider/i
    );
    await user.type(providerInput, "openai");

    // Fill in model configuration
    const modelNameInput = screen.getByPlaceholderText(/model-name-1/i);
    await user.type(modelNameInput, "gpt-4");

    // Set default model (there are 2 inputs with this placeholder - default and fast)
    const defaultModelInputs = screen.getAllByPlaceholderText(/e\.g\. gpt-4/i);
    await user.type(defaultModelInputs[0], "gpt-4");

    // Submit
    const submitButton = screen.getByRole("button", { name: /enable/i });
    await user.click(submitButton);

    // Verify error popup
    await waitFor(() => {
      expect(mockSetPopup).toHaveBeenCalledWith({
        type: "error",
        message: "Failed to enable provider: Database error",
      });
    });

    // Verify onClose was NOT called
    expect(mockOnClose).not.toHaveBeenCalled();
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

    render(
      <CustomLLMProviderUpdateForm
        onClose={mockOnClose}
        setPopup={mockSetPopup}
      />
    );

    // Fill basic fields
    const nameInput = screen.getByPlaceholderText(/display name/i);
    await user.type(nameInput, "Cloudflare Provider");

    const providerInput = screen.getByPlaceholderText(
      /name of the custom provider/i
    );
    await user.type(providerInput, "cloudflare");

    // Click "Add New" button for custom config (there are 2 "Add New" buttons - one for custom config, one for models)
    // The custom config "Add New" appears first
    const addNewButtons = screen.getAllByRole("button", { name: /add new/i });
    const customConfigAddButton = addNewButtons[0]; // First "Add New" is for custom config
    await user.click(customConfigAddButton);

    // Fill in custom config key-value pair
    const customConfigInputs = screen.getAllByRole("textbox");
    const keyInput = customConfigInputs.find(
      (input) => input.getAttribute("name") === "custom_config_list[0][0]"
    );
    const valueInput = customConfigInputs.find(
      (input) => input.getAttribute("name") === "custom_config_list[0][1]"
    );

    expect(keyInput).toBeDefined();
    expect(valueInput).toBeDefined();

    await user.type(keyInput!, "CLOUDFLARE_ACCOUNT_ID");
    await user.type(valueInput!, "my-account-id-123");

    // Fill in model configuration
    const modelNameInput = screen.getByPlaceholderText(/model-name-1/i);
    await user.type(modelNameInput, "@cf/meta/llama-2-7b-chat-int8");

    // Set default model (there are 2 inputs with this placeholder - default and fast)
    const defaultModelInputs = screen.getAllByPlaceholderText(/e\.g\. gpt-4/i);
    await user.type(defaultModelInputs[0], "@cf/meta/llama-2-7b-chat-int8");

    // Submit
    const submitButton = screen.getByRole("button", { name: /enable/i });
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
