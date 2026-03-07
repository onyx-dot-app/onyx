/**
 * Unit tests for OpenAIOnboardingForm component
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { OpenAIOnboardingForm } from "../OpenAIOnboardingForm";
import {
  createMockOnboardingState,
  createMockOnboardingActions,
  createMockFetchResponses,
  MOCK_PROVIDERS,
} from "./testHelpers";

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

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

const mockFetchModels = jest.fn().mockResolvedValue({
  models: [
    {
      name: "gpt-5.2",
      is_visible: true,
      max_input_tokens: 128000,
      supports_image_input: true,
    },
    {
      name: "gpt-5-mini",
      is_visible: true,
      max_input_tokens: 128000,
      supports_image_input: true,
    },
    {
      name: "o1",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: true,
    },
    {
      name: "o3-mini",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: false,
    },
    {
      name: "gpt-4o",
      is_visible: true,
      max_input_tokens: 128000,
      supports_image_input: true,
    },
    {
      name: "gpt-4o-mini",
      is_visible: true,
      max_input_tokens: 128000,
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

describe("OpenAIOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.openai,
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
      render(<OpenAIOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up GPT")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<OpenAIOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(/Connect to OpenAI and set up your ChatGPT models/i)
      ).toBeInTheDocument();
    });

    test("renders API key field", () => {
      render(<OpenAIOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<OpenAIOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("renders link to OpenAI API keys page", () => {
      render(<OpenAIOnboardingForm {...defaultProps} />);

      const link = screen.getByRole("link", { name: /api key/i });
      expect(link).toHaveAttribute(
        "href",
        "https://platform.openai.com/api-keys"
      );
    });

    test("does not render when closed", () => {
      render(<OpenAIOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<OpenAIOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is enabled when API key is filled (default model is pre-selected)", async () => {
      const user = setupUser();
      render(<OpenAIOnboardingForm {...defaultProps} />);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-test-key");

      // Button should be enabled because default model (gpt-5.2) is pre-selected
      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).not.toBeDisabled();
    });
  });

  describe("Form Submission", () => {
    async function fillForm(user: ReturnType<typeof setupUser>) {
      // Fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-test-key-123");

      // OpenAI form uses static models from llmDescriptor, no fetch button exists
      // Verify fetchModels is not called
      expect(mockFetchModels).not.toHaveBeenCalled();

      // Select a model from the dropdown
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "gpt-5.2");
    }

    test("calls API test endpoint on submit", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<OpenAIOnboardingForm {...defaultProps} />);

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
            headers: { "Content-Type": "application/json" },
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

      render(<OpenAIOnboardingForm {...defaultProps} />);

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/provider?is_creation=true",
          expect.objectContaining({
            method: "PUT",
            headers: { "Content-Type": "application/json" },
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
        <OpenAIOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      await fillForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("updates onboarding data with openai provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <OpenAIOnboardingForm
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
            llmProviders: expect.arrayContaining(["openai"]),
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

      // OpenAI form uses static models from llmDescriptor, no fetch button exists
      // Verify fetchModels is not called
      expect(mockFetchModels).not.toHaveBeenCalled();

      // Select a model from the dropdown
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "gpt-5.2");
    }

    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Invalid API key provided")
      );

      render(<OpenAIOnboardingForm {...defaultProps} />);

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Invalid API key provided/i)
        ).toBeInTheDocument();
      });
    });

    test("does not close modal on error", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch.mockResolvedValueOnce(mockResponses.testApiError("Error"));

      render(
        <OpenAIOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
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
        <OpenAIOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
