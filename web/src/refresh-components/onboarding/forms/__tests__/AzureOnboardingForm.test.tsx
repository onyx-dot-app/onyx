/**
 * Unit tests for AzureOnboardingForm component
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { AzureOnboardingForm } from "../AzureOnboardingForm";
import {
  createMockOnboardingState,
  createMockOnboardingActions,
  createMockFetchResponses,
  MOCK_PROVIDERS,
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

// Mock ProviderIcon
jest.mock("@/app/admin/configuration/llm/ProviderIcon", () => ({
  ProviderIcon: ({ provider }: { provider: string }) => (
    <span data-testid={`provider-icon-${provider}`}>Icon</span>
  ),
}));

// Mock azureTargetUri
jest.mock("@/lib/azureTargetUri", () => ({
  isValidAzureTargetUri: jest.fn((uri: string) => {
    // Simple validation for tests
    return (
      uri.includes("cognitiveservices.azure.com") && uri.includes("api-version")
    );
  }),
  parseAzureTargetUri: jest.fn((uri: string) => {
    const url = new URL(uri);
    const apiVersion = url.searchParams.get("api-version");
    const pathParts = url.pathname.split("/");
    const deploymentsIndex = pathParts.indexOf("deployments");
    const deploymentName =
      deploymentsIndex !== -1 ? pathParts[deploymentsIndex + 1] : null;
    return {
      url,
      apiVersion,
      deploymentName,
    };
  }),
}));

describe("AzureOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.azure,
    onboardingState: mockOnboardingState,
    onboardingActions: mockOnboardingActions,
    open: true,
    onOpenChange: jest.fn(),
  };

  const validTargetUri =
    "https://my-resource.cognitiveservices.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2024-02-01";

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe("Rendering", () => {
    test("renders modal with correct title", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up Azure OpenAI")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(
          /Connect to Microsoft Azure and set up your Azure OpenAI models/i
        )
      ).toBeInTheDocument();
    });

    test("renders Target URI field", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Target URI")).toBeInTheDocument();
    });

    test("renders API key field", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("renders link to Azure OpenAI portal", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      const links = screen.getAllByRole("link");
      const azureLink = links.find(
        (link) => link.getAttribute("href") === "https://oai.azure.com"
      );
      expect(azureLink).toBeInTheDocument();
    });

    test("does not render when closed", () => {
      render(<AzureOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<AzureOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is disabled with only target URI", async () => {
      const user = setupUser();
      render(<AzureOnboardingForm {...defaultProps} />);

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("validates target URI format", async () => {
      const user = setupUser();
      render(<AzureOnboardingForm {...defaultProps} />);

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, "invalid-uri");

      // Trigger blur to validate
      await user.tab();

      // Should show validation error
      await waitFor(() => {
        expect(
          screen.getByText(/Target URI must be a valid URL/i)
        ).toBeInTheDocument();
      });
    });
  });

  describe("Form Submission", () => {
    test("calls API test endpoint with azure provider", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<AzureOnboardingForm {...defaultProps} />);

      // Fill target URI
      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      // Fill API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "azure-api-key-123");

      // Fill model
      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
            body: expect.stringContaining('"provider":"azure"'),
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

      render(<AzureOnboardingForm {...defaultProps} />);

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "azure-api-key-123");

      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

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
        <AzureOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "azure-api-key-123");

      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("updates onboarding data with azure provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <AzureOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "azure-api-key-123");

      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(updateData).toHaveBeenCalledWith(
          expect.objectContaining({
            llmProviders: expect.arrayContaining(["azure"]),
          })
        );
      });
    });
  });

  describe("Error Handling", () => {
    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Invalid Azure credentials")
      );

      render(<AzureOnboardingForm {...defaultProps} />);

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "invalid-key");

      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Invalid Azure credentials/i)
        ).toBeInTheDocument();
      });
    });

    test("does not close modal on error", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch.mockResolvedValueOnce(mockResponses.testApiError("Error"));

      render(
        <AzureOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const targetUriInput = screen.getByPlaceholderText(/cognitiveservices/i);
      await user.type(targetUriInput, validTargetUri);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "invalid-key");

      const modelInput = screen.getByPlaceholderText(
        "Select or type a model name"
      );
      await user.type(modelInput, "gpt-4");

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
        <AzureOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
