/**
 * Unit tests for BedrockOnboardingForm component
 * Tests different authentication methods: IAM, Access Key, Long-term API Key
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import { BedrockOnboardingForm } from "../BedrockOnboardingForm";
import {
  createMockOnboardingState,
  createMockOnboardingActions,
  createMockFetchResponses,
  MOCK_PROVIDERS,
} from "./testHelpers";

// Polyfill for Radix UI Select which uses methods not implemented in jsdom
beforeAll(() => {
  Element.prototype.hasPointerCapture = jest.fn().mockReturnValue(false);
  Element.prototype.setPointerCapture = jest.fn();
  Element.prototype.releasePointerCapture = jest.fn();
  Element.prototype.scrollIntoView = jest.fn();
});

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
    { name: "anthropic.claude-3-sonnet", is_visible: true },
    { name: "anthropic.claude-3-haiku", is_visible: true },
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

describe("BedrockOnboardingForm", () => {
  const mockOnboardingState = createMockOnboardingState();
  const mockOnboardingActions = createMockOnboardingActions();
  const mockResponses = createMockFetchResponses();

  const defaultProps = {
    llmDescriptor: MOCK_PROVIDERS.bedrock,
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
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText("Set up Amazon Bedrock")).toBeInTheDocument();
    });

    test("renders description", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(
        screen.getByText(
          /Connect to AWS and set up your Amazon Bedrock models/i
        )
      ).toBeInTheDocument();
    });

    test("renders AWS Region field", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(screen.getByText("AWS Region")).toBeInTheDocument();
    });

    test("renders Authentication Method field", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Authentication Method")).toBeInTheDocument();
    });

    test("renders default model field", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(screen.getByText("Default Model")).toBeInTheDocument();
    });

    test("does not render when closed", () => {
      render(<BedrockOnboardingForm {...defaultProps} open={false} />);

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("Authentication Method - Access Key (Default)", () => {
    test("shows Access Key fields by default", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(screen.getByText("AWS Access Key ID")).toBeInTheDocument();
      expect(screen.getByText("AWS Secret Access Key")).toBeInTheDocument();
    });

    test("renders Access Key ID placeholder", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      expect(
        screen.getByPlaceholderText("AKIAIOSFODNN7EXAMPLE")
      ).toBeInTheDocument();
    });
  });

  describe("Authentication Method - IAM Role", () => {
    test("shows IAM info message when IAM selected", async () => {
      const user = setupUser();
      render(<BedrockOnboardingForm {...defaultProps} />);

      // Click on the auth method dropdown - it's the second combobox (first is region)
      const comboboxes = screen.getAllByRole("combobox");
      const authMethodTrigger = comboboxes[1]!; // Second combobox is auth method
      await user.click(authMethodTrigger);

      // Select IAM Role option
      const iamOption = screen.getByRole("option", { name: /iam role/i });
      await user.click(iamOption);

      // Should show IAM info message
      await waitFor(() => {
        expect(
          screen.getByText(/Onyx will use the IAM role attached/i)
        ).toBeInTheDocument();
      });
    });

    test("hides Access Key fields when IAM selected", async () => {
      const user = setupUser();
      render(<BedrockOnboardingForm {...defaultProps} />);

      // Click on the auth method dropdown - it's the second combobox
      const comboboxes = screen.getAllByRole("combobox");
      const authMethodTrigger = comboboxes[1]!;
      await user.click(authMethodTrigger);

      const iamOption = screen.getByRole("option", { name: /iam role/i });
      await user.click(iamOption);

      await waitFor(() => {
        expect(screen.queryByText("AWS Access Key ID")).not.toBeInTheDocument();
        expect(
          screen.queryByText("AWS Secret Access Key")
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("Authentication Method - Long-term API Key", () => {
    test("shows Long-term API Key field when selected", async () => {
      const user = setupUser();
      render(<BedrockOnboardingForm {...defaultProps} />);

      // Click on the auth method dropdown - it's the second combobox
      const comboboxes = screen.getAllByRole("combobox");
      const authMethodTrigger = comboboxes[1]!;
      await user.click(authMethodTrigger);

      const longTermOption = screen.getByRole("option", {
        name: /long-term api key/i,
      });
      await user.click(longTermOption);

      await waitFor(() => {
        expect(
          screen.getByText("AWS Bedrock Long-term API Key")
        ).toBeInTheDocument();
      });
    });
  });

  describe("Form Validation", () => {
    test("submit button is disabled when form is empty", () => {
      render(<BedrockOnboardingForm {...defaultProps} />);

      const submitButton = screen.getByTestId("submit-button");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("Form Submission - Access Key", () => {
    async function fillBedrockForm(user: ReturnType<typeof setupUser>) {
      // Select region - first combobox
      const comboboxes = screen.getAllByRole("combobox");
      const regionTrigger = comboboxes[0]!;
      await user.click(regionTrigger);
      const regionOption = screen.getByRole("option", { name: /us-east-1/i });
      await user.click(regionOption);

      // Fill Access Key ID
      const accessKeyInput = screen.getByPlaceholderText(
        "AKIAIOSFODNN7EXAMPLE"
      );
      await user.type(accessKeyInput, "AKIAIOSFODNN7EXAMPLE");

      // Fill Secret Access Key
      const secretKeyInput = screen.getByPlaceholderText(
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
      );
      await user.type(
        secretKeyInput,
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
      );

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

      // Fill model - use the textbox with the specific placeholder
      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "anthropic.claude-3-sonnet");
    }

    test("submits with Access Key credentials", async () => {
      const user = setupUser();

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(<BedrockOnboardingForm {...defaultProps} />);

      await fillBedrockForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/admin/llm/test",
          expect.objectContaining({
            method: "POST",
            body: expect.stringContaining('"provider":"bedrock"'),
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
        <BedrockOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      await fillBedrockForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("updates onboarding data with bedrock provider", async () => {
      const user = setupUser();
      const updateData = jest.fn();
      const mockActions = createMockOnboardingActions({ updateData });

      mockFetch
        .mockResolvedValueOnce(mockResponses.testApiSuccess)
        .mockResolvedValueOnce(mockResponses.createProviderSuccess(1))
        .mockResolvedValueOnce(mockResponses.setDefaultSuccess);

      render(
        <BedrockOnboardingForm
          {...defaultProps}
          onboardingActions={mockActions}
        />
      );

      await fillBedrockForm(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(updateData).toHaveBeenCalledWith(
          expect.objectContaining({
            llmProviders: expect.arrayContaining(["bedrock"]),
          })
        );
      });
    });
  });

  describe("Error Handling", () => {
    async function fillFormForErrorTest(user: ReturnType<typeof setupUser>) {
      // Select region - first combobox
      const comboboxes = screen.getAllByRole("combobox");
      const regionTrigger = comboboxes[0]!;
      await user.click(regionTrigger);
      const regionOption = screen.getByRole("option", { name: /us-east-1/i });
      await user.click(regionOption);

      // Fill credentials
      const accessKeyInput = screen.getByPlaceholderText(
        "AKIAIOSFODNN7EXAMPLE"
      );
      await user.type(accessKeyInput, "invalid-key");

      const secretKeyInput = screen.getByPlaceholderText(
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
      );
      await user.type(secretKeyInput, "invalid-secret");

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

      const modelInput = screen.getByPlaceholderText("Select a model");
      await user.type(modelInput, "anthropic.claude-3-sonnet");
    }

    test("displays error message when API test fails", async () => {
      const user = setupUser();

      mockFetch.mockResolvedValueOnce(
        mockResponses.testApiError("Invalid AWS credentials")
      );

      render(<BedrockOnboardingForm {...defaultProps} />);

      await fillFormForErrorTest(user);

      const submitButton = screen.getByTestId("submit-button");
      await user.click(submitButton);

      await waitFor(() => {
        expect(
          screen.getByText(/Invalid AWS credentials/i)
        ).toBeInTheDocument();
      });
    });
  });

  describe("Modal Controls", () => {
    test("calls onOpenChange when close button clicked", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();

      render(
        <BedrockOnboardingForm {...defaultProps} onOpenChange={onOpenChange} />
      );

      const closeButton = screen.getByTestId("close-button");
      await user.click(closeButton);

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
