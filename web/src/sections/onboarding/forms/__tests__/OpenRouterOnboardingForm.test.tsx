/**
 * Unit tests for OpenRouterOnboardingForm component
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { OpenRouterOnboardingForm } from "../OpenRouterOnboardingForm";
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
    { name: "openai/gpt-4", is_visible: true },
    { name: "anthropic/claude-3-opus", is_visible: true },
    { name: "meta-llama/llama-3-70b", is_visible: true },
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

describe("OpenRouterOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.openrouter,
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
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up OpenRouter")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(
          /Connect to OpenRouter and set up your OpenRouter models/i
        )
      ).toBeInTheDocument();
    });

    test("renders API key field", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("renders link to OpenRouter settings", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      const link = screen.getByRole("link", { name: /api key/i });
      expect(link).toHaveAttribute(
        "href",
        "https://openrouter.ai/settings/keys"
      );
    });

    test("does not render when closed", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });

    test("submit button is disabled when only API key is filled", async () => {
      const user = setupUser();
      render(<OpenRouterOnboardingForm {...defaultProps} />);

      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-or-test-key");

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Submission", () => {
    async function fillFormAndFetchModels(user: ReturnType<typeof setupUser>) {
      // First fill in API key
      const apiKeyInput = screen.getByPlaceholderText("");
      await user.type(apiKeyInput, "sk-or-test-key-123");

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

      // Now select a model from the dropdown (it should be enabled now)
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "openai/gpt-4");
    }

    test("calls API test endpoint with openrouter provider", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<OpenRouterOnboardingForm {...defaultProps} />);

      await fillFormAndFetchModels(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
            body: expect.stringContaining('"provider":"openrouter"'),
          })
        );
      });
    });

    test("includes correct api_base in submission", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<OpenRouterOnboardingForm {...defaultProps} />);

      await fillFormAndFetchModels(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/provider?is_creation=true",
          expect.objectContaining({
            method: "PUT",
            body: expect.stringContaining("https://openrouter.ai/api/v1"),
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
        <OpenRouterOnboardingForm
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

    test("updates onboarding data with openrouter provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <OpenRouterOnboardingForm
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
            llmProviders: expect.arrayContaining(["openrouter"]),
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
      await user.type(modelInput, "openai/gpt-4");
    }

    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Invalid OpenRouter API key")
      );

      render(<OpenRouterOnboardingForm {...defaultProps} />);

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Invalid OpenRouter API key/i)
        ).toBeInTheDocument();
      });
    });

    test("does not close modal on error", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      mockFetch.mockResolvedValueOnce(mockResponses.testApiError("Error"));

      render(
        <OpenRouterOnboardingForm
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
        <OpenRouterOnboardingForm
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
