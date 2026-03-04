/**
 * Unit tests for OllamaOnboardingForm component
 * Tests both self-hosted and cloud tabs
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { OllamaOnboardingForm } from "../OllamaOnboardingForm";
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
const mockFetchModels = jest.fn().mockResolvedValue({
  models: [
    { name: "llama2", is_visible: true },
    { name: "mistral", is_visible: true },
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

describe("OllamaOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.ollama,
    onboardingState: mockOnboardingState,
    onboardingActions: mockOnboardingActions,
    open: true,
    onOpenChange: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    mockFetchModels.mockClear();
  });

  describe("Rendering", () => {
    test("renders modal with correct title", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up Ollama")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(/Connect to your Ollama models/i)
      ).toBeInTheDocument();
    });

    test("renders tabs for self-hosted and cloud", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      expect(
        screen.getByRole("tab", { name: /self-hosted/i })
      ).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /cloud/i })).toBeInTheDocument();
    });

    test("self-hosted tab is selected by default", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      const selfHostedTab = screen.getByRole("tab", { name: /self-hosted/i });
      expect(selfHostedTab).toHaveAttribute("data-state", "active");
    });

    test("does not render when closed", () => {
      render(<OllamaOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Self-Hosted Tab", () => {
    test("renders API Base URL field", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Base URL")).toBeInTheDocument();
    });

    test("shows default API base URL placeholder", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      const input = screen.getByPlaceholderText("http://127.0.0.1:11434");
      expect(input).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });
  });

  describe("Cloud Tab", () => {
    test("switches to cloud tab when clicked", async () => {
      const user = setupUser();
      render(<OllamaOnboardingForm {...defaultProps} />);

      const cloudTab = screen.getByRole("tab", { name: /cloud/i });
      await user.click(cloudTab);

      expect(cloudTab).toHaveAttribute("data-state", "active");
    });

    test("shows API Key field in cloud tab", async () => {
      const user = setupUser();
      render(<OllamaOnboardingForm {...defaultProps} />);

      const cloudTab = screen.getByRole("tab", { name: /cloud/i });
      await user.click(cloudTab);

      // In cloud tab, we should see API Key label
      const apiKeyLabels = screen.getAllByText("API Key");
      expect(apiKeyLabels.length).toBeGreaterThan(0);
    });

    test("shows link to Ollama cloud", async () => {
      const user = setupUser();
      render(<OllamaOnboardingForm {...defaultProps} />);

      const cloudTab = screen.getByRole("tab", { name: /cloud/i });
      await user.click(cloudTab);

      const link = screen.getByRole("link", { name: /api key/i });
      expect(link).toHaveAttribute("href", "https://ollama.com");
    });
  });

  describe("Form Validation - Self-Hosted", () => {
    test("submit button is disabled when form is empty", () => {
      render(<OllamaOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Validation - Cloud", () => {
    test("submit button is disabled when cloud form is empty", async () => {
      const user = setupUser();
      render(<OllamaOnboardingForm {...defaultProps} />);

      const cloudTab = screen.getByRole("tab", { name: /cloud/i });
      await user.click(cloudTab);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Submission - Self-Hosted", () => {
    test("submits with self-hosted URL", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<OllamaOnboardingForm {...defaultProps} />);

      // Fill API base
      const apiBaseInput = screen.getByPlaceholderText(
        "http://127.0.0.1:11434"
      );
      await user.clear(apiBaseInput);
      await user.type(apiBaseInput, "http://localhost:11434");

      // Fill model
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "llama2");

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

    test("closes modal on successful self-hosted submission", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <OllamaOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const apiBaseInput = screen.getByPlaceholderText(
        "http://127.0.0.1:11434"
      );
      await user.clear(apiBaseInput);
      await user.type(apiBaseInput, "http://localhost:11434");

      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "llama2");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });
  });

  describe("Form Submission - Cloud", () => {
    test("submits with cloud API key", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<OllamaOnboardingForm {...defaultProps} />);

      // Switch to cloud tab
      const cloudTab = screen.getByRole("tab", { name: /cloud/i });
      await user.click(cloudTab);

      // Fill API key
      const apiKeyInput = screen.getByLabelText(/api key/i);
      await user.type(apiKeyInput, "ollama-cloud-key-123");

      // Fill model
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "llama2");

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
  });

  describe("Provider Updates", () => {
    test("updates onboarding data with ollama_chat provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <OllamaOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      const apiBaseInput = screen.getByPlaceholderText(
        "http://127.0.0.1:11434"
      );
      await user.clear(apiBaseInput);
      await user.type(apiBaseInput, "http://localhost:11434");

      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "llama2");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(updateData).toHaveBeenCalledWith(
          expect.objectContaining({
            llmProviders: expect.arrayContaining(["ollama_chat"]),
          })
        );
      });
    });
  });

  describe("Error Handling", () => {
    test("displays error message when connection fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Failed to connect to Ollama")
      );

      render(<OllamaOnboardingForm {...defaultProps} />);

      const apiBaseInput = screen.getByPlaceholderText(
        "http://127.0.0.1:11434"
      );
      await user.clear(apiBaseInput);
      await user.type(apiBaseInput, "http://invalid-host:11434");

      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "llama2");

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Failed to connect to Ollama/i)
        ).toBeInTheDocument();
      });
    });
  });

  describe("Modal Controls", () => {
    test("calls onOpenChange when close button clicked", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      render(
        <OllamaOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
