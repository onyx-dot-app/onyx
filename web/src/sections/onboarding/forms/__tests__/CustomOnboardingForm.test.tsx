/**
 * Unit tests for CustomOnboardingForm component
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { CustomOnboardingForm } from "../CustomOnboardingForm";
import {
  createMockOnboardingState,
  createMockOnboardingActions,
  createMockFetchResponses,
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

// Mock fetchModels utility
jest.mock("@/app/admin/configuration/llm/utils", () => ({
  canProviderFetchModels: jest.fn().mockReturnValue(false),
  fetchModels: jest.fn().mockResolvedValue({
    models: [],
    error: null,
  }),
}));

describe("CustomOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
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
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(
        screen.getByText("Set up Custom LLM Provider")
      ).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(
          /Connect models from other providers or your self-hosted models/i
        )
      ).toBeInTheDocument();
    });

    test("renders Provider Name field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Provider Name")).toBeInTheDocument();
    });

    test("renders API Base URL field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Base URL")).toBeInTheDocument();
    });

    test("renders API Version field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Version")).toBeInTheDocument();
    });

    test("renders API Key field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("renders Additional Configs field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Additional Configs")).toBeInTheDocument();
    });

    test("renders Model Configs field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Model Configs")).toBeInTheDocument();
    });

    test("renders Default Model field", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("renders link to LiteLLM providers documentation", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      const links = screen.getAllByRole("link", { name: /litellm/i });
      const providerLink = links.find(
        (link) =>
          link.getAttribute("href") === "https://docs.litellm.ai/docs/providers"
      );
      expect(providerLink).toBeInTheDocument();
    });

    test("does not render when closed", () => {
      render(<CustomOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is disabled when only provider name is filled", async () => {
      const user = setupUser();
      render(<CustomOnboardingForm {...defaultProps} />);

      const providerInput = screen.getByPlaceholderText(
        /E.g. openai, anthropic/i
      );
      await user.type(providerInput, "custom-provider");

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Submission", () => {
    async function fillCustomForm(user: ReturnType<typeof setupUser>) {
      // Fill provider name
      const providerInput = screen.getByPlaceholderText(
        /E.g. openai, anthropic/i
      );
      await user.type(providerInput, "groq");

      // Fill model config - the KeyValueInput uses aria-label "Model Name 1" for first row
      const modelNameInput = screen.getByLabelText("Model Name 1");
      await user.type(modelNameInput, "llama-3-70b");

      // Fill default model (should match one of the model configs)
      const defaultModelInput = screen.getByPlaceholderText("model-name");
      await user.type(defaultModelInput, "llama-3-70b");
    }

    test("calls API test endpoint with custom provider config", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<CustomOnboardingForm {...defaultProps} />);

      await fillCustomForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
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
        <CustomOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      await fillCustomForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("updates onboarding data with custom provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <CustomOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      await fillCustomForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(updateData).toHaveBeenCalledWith(
          expect.objectContaining({
            llmProviders: expect.arrayContaining(["custom"]),
          })
        );
      });
    });
  });

  describe("Optional Fields", () => {
    test("API Base URL shows optional indicator", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      // The field label should have an "(Optional)" indicator
      const apiBaseLabel = screen.getByText("API Base URL").closest("label");
      expect(apiBaseLabel).toHaveTextContent("(Optional)");
    });

    test("API Version shows optional indicator", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      // The field label should have an "(Optional)" indicator
      const apiVersionLabel = screen.getByText("API Version").closest("label");
      expect(apiVersionLabel).toHaveTextContent("(Optional)");
    });

    test("API Key shows optional indicator", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      // The field label should have an "(Optional)" indicator
      const apiKeyLabel = screen.getByText("API Key").closest("label");
      expect(apiKeyLabel).toHaveTextContent("(Optional)");
    });

    test("Additional Configs shows optional indicator", () => {
      render(<CustomOnboardingForm {...defaultProps} />);

      // The field label should have an "(Optional)" indicator
      const additionalConfigsLabel = screen
        .getByText("Additional Configs")
        .closest("label");
      expect(additionalConfigsLabel).toHaveTextContent("(Optional)");
    });
  });

  describe("Error Handling", () => {
    async function fillFormForErrorTest(user: ReturnType<typeof setupUser>) {
      // Fill provider name
      const providerInput = screen.getByPlaceholderText(
        /E.g. openai, anthropic/i
      );
      await user.type(providerInput, "invalid-provider");

      // Fill model config - the KeyValueInput uses aria-label "Model Name 1"
      const modelNameInput = screen.getByLabelText("Model Name 1");
      await user.type(modelNameInput, "some-model");

      // Fill default model
      const defaultModelInput = screen.getByPlaceholderText("model-name");
      await user.type(defaultModelInput, "some-model");
    }

    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Provider configuration failed")
      );

      render(<CustomOnboardingForm {...defaultProps} />);

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Provider configuration failed/i)
        ).toBeInTheDocument();
      });
    });

    test("does not close modal on error", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch.mockResolvedValueOnce(mockResponses.testApiError("Error"));

      render(
        <CustomOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
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
        <CustomOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
