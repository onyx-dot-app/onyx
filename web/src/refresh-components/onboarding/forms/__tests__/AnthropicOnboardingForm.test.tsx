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
    { name: "claude-3-opus", is_visible: true },
    { name: "claude-3-sonnet", is_visible: true },
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

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<AnthropicOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is disabled when only API key is filled", async () => {
      const user = setupUser();
      render(<AnthropicOnboardingForm {...defaultProps} />);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-ant-test-key");

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Submission", () => {
    async function fillFormAndFetchModels(user: ReturnType<typeof setupUser>) {
      // First fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-ant-test-key-123");

      // Click fetch models button - find it by looking for icon button with data-state
      // The IconButton with tooltip "Fetch available models" has data-state attribute
      const buttons = screen.getAllByRole("button");
      const fetchButton = buttons.find(
        (btn) => btn.getAttribute("data-state") === "closed"
      );
      if (fetchButton) {
        await user.click(fetchButton);
      }

      // Wait for models to be fetched
      await waitFor(() => {
        expect(mockFetchModels).toHaveBeenCalled();
      });

      // Now select a model from the dropdown (it should be enabled now)
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "claude-3-opus");
    }

    test("calls API test endpoint with anthropic provider", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1));

      render(<AnthropicOnboardingForm {...defaultProps} />);

      await fillFormAndFetchModels(user);

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
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1));

      render(<AnthropicOnboardingForm {...defaultProps} />);

      await fillFormAndFetchModels(user);

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
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1));

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onOpenChange={onOpenChange}
        />
      );

      await fillFormAndFetchModels(user);

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
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1));

      render(
        <AnthropicOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      await fillFormAndFetchModels(user);

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
      // First fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "invalid-key");

      // Click fetch models button - find it by looking for icon button with data-state
      const buttons = screen.getAllByRole("button");
      const fetchButton = buttons.find(
        (btn) => btn.getAttribute("data-state") === "closed"
      );
      if (fetchButton) {
        await user.click(fetchButton);
      }

      // Wait for models to be fetched
      await waitFor(() => {
        expect(mockFetchModels).toHaveBeenCalled();
      });

      // Now select a model from the dropdown
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "claude-3-opus");
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
