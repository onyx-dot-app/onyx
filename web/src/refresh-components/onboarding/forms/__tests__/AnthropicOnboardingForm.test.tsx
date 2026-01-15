/**
 * Unit tests for AnthropicOnboardingForm component
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { AnthropicOnboardingForm } from "../AnthropicOnboardingForm";
import {
  createMockOnboardingState,
  createMockOnboardingActions,
  createMockFetchResponses,
  MOCK_PROVIDERS,
  ANTHROPIC_DEFAULT_VISIBLE_MODELS,
} from "./testHelpers";

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock the ProviderModal component
jest.mock("@/components/modals/ProviderModal", () => ({
  __esModule: true,
  default: ({
    children,
    open,
    onOpenChange,
    title,
    description,
    onSubmit,
    submitDisabled,
    isSubmitting,
  }: any) => {
    if (!open) return null;
    return (
      <div role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
        {children}
        <button
          onClick={onSubmit}
          disabled={submitDisabled}
          data-testid="submit-button"
        >
          {isSubmitting ? "Submitting..." : "Submit"}
        </button>
        <button onClick={() => onOpenChange(false)} data-testid="close-button">
          Close
        </button>
      </div>
    );
  },
}));

// Mock fetchModels utility - returns the curated Anthropic visible models
// that match ANTHROPIC_VISIBLE_MODEL_NAMES from backend
const mockFetchModels = jest.fn().mockResolvedValue({
  models: [
    {
      name: "claude-opus-4-5",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: true,
    },
    {
      name: "claude-sonnet-4-5",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: true,
    },
    {
      name: "claude-haiku-4-5",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: true,
    },
  ],
  error: null,
});

jest.mock("@/app/admin/configuration/llm/utils", () => ({
  canProviderFetchModels: jest.fn().mockReturnValue(true),
  fetchModels: (...args: any[]) => mockFetchModels(...args),
}));

// Mock ProviderIcon
jest.mock("@/app/admin/configuration/llm/ProviderIcon", () => ({
  ProviderIcon: ({ provider }: { provider: string }) => (
    <span data-testid={`provider-icon-${provider}`}>Icon</span>
  ),
}));

describe("AnthropicOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.anthropic,
    onboardingState: mockOnboardingState,
    onboardingActions: mockOnboardingActions,
    open: true,
    onOpenChange: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe("Rendering", () => {
    test("renders modal with correct title", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up Claude")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(/Connect to Anthropic and set up your Claude models/i)
      ).toBeInTheDocument();
    });

    test("renders API key field", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("renders link to Anthropic console", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      const link = screen.getByRole("link", { name: /api key/i });
      expect(link).toHaveAttribute(
        "href",
        "https://console.anthropic.com/dashboard"
      );
    });

    test("does not render when closed", () => {
      render(<AnthropicOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Default Available Models", () => {
    /**
     * This test verifies that the exact curated list of Anthropic visible models
     * matches what's returned from /api/admin/llm/built-in/options.
     * The expected models are defined in ANTHROPIC_VISIBLE_MODEL_NAMES in
     * backend/onyx/llm/llm_provider_options.py
     */
    test("llmDescriptor contains the correct default visible models from built-in options", () => {
      const expectedModelNames = [
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
      ];

      // Verify MOCK_PROVIDERS.anthropic has the correct model configurations
      const actualModelNames = MOCK_PROVIDERS.anthropic.known_models.map(
        (config) => config.name
      );

      // Check that all expected models are present
      expect(actualModelNames).toEqual(
        expect.arrayContaining(expectedModelNames)
      );

      // Check that only the expected models are present (no extras)
      expect(actualModelNames).toHaveLength(expectedModelNames.length);

      // Verify each model has is_visible set to true
      MOCK_PROVIDERS.anthropic.known_models.forEach((config) => {
        expect(config.is_visible).toBe(true);
      });
    });

    test("ANTHROPIC_DEFAULT_VISIBLE_MODELS matches backend ANTHROPIC_VISIBLE_MODEL_NAMES", () => {
      // These are the exact model names from backend/onyx/llm/llm_provider_options.py
      // ANTHROPIC_VISIBLE_MODEL_NAMES = {"claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"}
      const backendVisibleModelNames = new Set([
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
      ]);

      const testHelperModelNames = new Set(
        ANTHROPIC_DEFAULT_VISIBLE_MODELS.map((m) => m.name)
      );

      expect(testHelperModelNames).toEqual(backendVisibleModelNames);
    });

    test("all default models are marked as visible", () => {
      ANTHROPIC_DEFAULT_VISIBLE_MODELS.forEach((model) => {
        expect(model.is_visible).toBe(true);
      });
    });

    test("default model claude-sonnet-4-5 is set correctly in component", () => {
      // The AnthropicOnboardingForm sets DEFAULT_DEFAULT_MODEL_NAME = "claude-sonnet-4-5"
      // Verify this model exists in the default visible models
      const defaultModelExists = ANTHROPIC_DEFAULT_VISIBLE_MODELS.some(
        (m) => m.name === "claude-sonnet-4-5"
      );
      expect(defaultModelExists).toBe(true);
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is enabled when API key is filled (default model is pre-selected)", async () => {
      const user = setupUser();
      render(<AnthropicOnboardingForm {...defaultProps} />);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-ant-test-key");

      // Button should be enabled because default model (claude-sonnet-4-5) is pre-selected
      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).not.toBeDisabled();
    });
  });

  describe("Form Submission", () => {
    async function fillForm(user: ReturnType<typeof setupUser>) {
      // Fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-ant-test-key-123");

      // Anthropic form uses static models from llmDescriptor, no fetch button exists
      // Verify fetchModels is not called
      expect(mockFetchModels).not.toHaveBeenCalled();

      // Select a model from the dropdown
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "claude-sonnet-4-5");
    }

    test("calls API test endpoint with anthropic provider", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<AnthropicOnboardingForm {...defaultProps} />);

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
            body: expect.stringContaining('"provider":"anthropic"'),
          })
        );
      });
    });

    test("creates provider after successful test", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<AnthropicOnboardingForm {...defaultProps} />);

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/provider?is_creation=true",
          expect.objectContaining({
            method: "PUT",
          })
        );
      });
    });

    test("closes modal on successful submission", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onOpenChange={onOpenChange}
        />
      );

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("updates onboarding data with anthropic provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(updateData).toHaveBeenCalledWith(
          expect.objectContaining({
            llmProviders: expect.arrayContaining(["anthropic"]),
          })
        );
      });
    });
  });

  describe("Error Handling", () => {
    async function fillFormForErrorTest(user: ReturnType<typeof setupUser>) {
      // Fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "invalid-key");

      // Anthropic form uses static models from llmDescriptor, no fetch button exists
      // Verify fetchModels is not called
      expect(mockFetchModels).not.toHaveBeenCalled();

      // Select a model from the dropdown
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "claude-sonnet-4-5");
    }

    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Invalid API key")
      );

      render(<AnthropicOnboardingForm {...defaultProps} />);

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/Invalid API key/i)).toBeInTheDocument();
      });
    });

    test("does not close modal on error", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch.mockResolvedValueOnce(mockResponses.testApiError("Error"));

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onOpenChange={onOpenChange}
        />
      );

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      expect(onOpenChange).not.toHaveBeenCalledWith(false);
    });
  });

  describe("Modal Controls", () => {
    test("calls onOpenChange when close button clicked", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onOpenChange={onOpenChange}
        />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
