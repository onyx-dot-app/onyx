/**
 * @jest-environment jsdom
 *
 * Integration Test: Input Prompts CRUD Workflow
 *
 * Tests complete user workflows for managing prompt shortcuts:
 * - Viewing list of prompts (Read)
 * - Creating new prompts (Create)
 * - Editing existing prompts (Update)
 * - Deleting/hiding prompts (Delete)
 * - Success/error notifications
 * - Real-time UI updates
 */
import React from "react";
import {
  render,
  screen,
  userEvent,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import InputPrompts from "./InputPrompts";

// Mock next/navigation
const mockBack = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    back: mockBack,
  }),
}));

describe("Input Prompts CRUD Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  const mockPrompts = [
    {
      id: 1,
      prompt: "Summarize",
      content: "Summarize the uploaded document and highlight key points.",
      is_public: false,
      active: true,
    },
    {
      id: 2,
      prompt: "Explain",
      content: "Explain this concept in simple terms.",
      is_public: true,
      active: true,
    },
    {
      id: 3,
      prompt: "Translate",
      content: "Translate this text to Spanish.",
      is_public: false,
      active: true,
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  describe("Read: Viewing Prompts", () => {
    it("fetches and displays list of prompts on page load", async () => {
      // Mock successful API response
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      // Page title and description are shown
      expect(screen.getByText(/prompt shortcuts/i)).toBeInTheDocument();
      expect(screen.getByText(/manage and customize/i)).toBeInTheDocument();

      // API is called to fetch prompts
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
      });

      // All prompts are displayed
      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
        expect(screen.getByText("Explain")).toBeInTheDocument();
        expect(screen.getByText("Translate")).toBeInTheDocument();
      });

      // Prompt contents are visible
      expect(
        screen.getByText(/summarize the uploaded document/i)
      ).toBeInTheDocument();
      expect(screen.getByText(/explain this concept/i)).toBeInTheDocument();
    });

    it("shows error message when fetching prompts fails", async () => {
      // Mock API error
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: false,
        status: 500,
      });

      render(<InputPrompts />);

      // User sees error notification
      await waitFor(() => {
        expect(
          screen.getByText(/failed to fetch prompt shortcuts/i)
        ).toBeInTheDocument();
      });
    });

    it("handles empty prompts list", async () => {
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => [],
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalled();
      });

      // No prompts are shown
      expect(screen.queryByText("Summarize")).not.toBeInTheDocument();

      // User can still create new prompt
      expect(screen.getByRole("button", { name: /add/i })).toBeInTheDocument();
    });
  });

  describe("Create: Adding New Prompts", () => {
    it("allows user to create a new prompt", async () => {
      const user = userEvent.setup();

      // Mock initial fetch
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      // User clicks "Add New Prompt" button
      const addButton = screen.getByRole("button", { name: /add.*prompt/i });
      await user.click(addButton);

      // Creation form appears
      expect(
        screen.getByPlaceholderText(/prompt shortcut.*e\.g\. summarize/i)
      ).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText(/actual prompt.*e\.g\. summarize the/i)
      ).toBeInTheDocument();

      // User fills out the form
      const shortcutInput = screen.getByPlaceholderText(/prompt shortcut/i);
      const contentInput = screen.getByPlaceholderText(/actual prompt/i);

      await user.type(shortcutInput, "Debug");
      await user.type(
        contentInput,
        "Help me debug this code and explain any issues."
      );

      expect(shortcutInput).toHaveValue("Debug");
      expect(contentInput).toHaveValue(
        "Help me debug this code and explain any issues."
      );

      // Mock successful creation
      const newPrompt = {
        id: 4,
        prompt: "Debug",
        content: "Help me debug this code and explain any issues.",
        is_public: false,
        active: true,
      };

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => newPrompt,
      });

      // User clicks "Create" button
      const createButton = screen.getByRole("button", { name: /create/i });
      await user.click(createButton);

      // API is called with correct data
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/input_prompt",
          expect.objectContaining({
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: "Debug",
              content: "Help me debug this code and explain any issues.",
              is_public: false,
            }),
          })
        );
      });

      // Success message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/prompt created successfully/i)
        ).toBeInTheDocument();
      });

      // New prompt appears in the list
      expect(screen.getByText("Debug")).toBeInTheDocument();
      expect(screen.getByText(/help me debug this code/i)).toBeInTheDocument();

      // Creation form is closed
      expect(
        screen.queryByPlaceholderText(/prompt shortcut/i)
      ).not.toBeInTheDocument();
    });

    it("allows user to cancel prompt creation", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      // User clicks add button
      const addButton = screen.getByRole("button", { name: /add.*prompt/i });
      await user.click(addButton);

      // User fills partial data
      await user.type(screen.getByPlaceholderText(/prompt shortcut/i), "Test");

      // User clicks cancel
      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      await user.click(cancelButton);

      // Form is closed
      expect(
        screen.queryByPlaceholderText(/prompt shortcut/i)
      ).not.toBeInTheDocument();

      // No API call was made
      expect(fetchSpy).toHaveBeenCalledTimes(1); // Only initial fetch
    });

    it("shows error when prompt creation fails", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      await user.click(screen.getByRole("button", { name: /add.*prompt/i }));

      await user.type(screen.getByPlaceholderText(/prompt shortcut/i), "Test");
      await user.type(
        screen.getByPlaceholderText(/actual prompt/i),
        "Test content"
      );

      // Mock failed creation
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: false,
        status: 400,
      });

      await user.click(screen.getByRole("button", { name: /create/i }));

      // Error message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/failed to create prompt/i)
        ).toBeInTheDocument();
      });

      // Prompt is not added to list
      expect(screen.queryByText("Test")).not.toBeInTheDocument();
    });
  });

  describe("Update: Editing Prompts", () => {
    it("allows user to edit a user-created prompt", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      // Find the "Summarize" prompt card
      const summarizeCard = screen
        .getByText("Summarize")
        .closest("div[class*='border']");

      // User clicks edit button (three dots menu)
      const editButton = within(summarizeCard!).getByRole("button", {
        name: /edit|more/i,
      });
      await user.click(editButton);

      // Dropdown menu appears with edit option
      const editMenuItem = screen.getByText(/edit/i);
      await user.click(editMenuItem);

      // Inputs become editable
      const shortcutInput = within(summarizeCard!).getByDisplayValue(
        "Summarize"
      );
      const contentInput = within(summarizeCard!).getByDisplayValue(
        /summarize the uploaded/i
      );

      // User modifies the content
      await user.clear(contentInput);
      await user.type(
        contentInput,
        "Summarize the document with bullet points."
      );

      expect(contentInput).toHaveValue(
        "Summarize the document with bullet points."
      );

      // Mock successful update
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => ({}),
      });

      // User clicks save button
      const saveButton = within(summarizeCard!).getByRole("button", {
        name: /save/i,
      });
      await user.click(saveButton);

      // API is called with updated data
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/input_prompt/1",
          expect.objectContaining({
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: "Summarize",
              content: "Summarize the document with bullet points.",
              active: true,
            }),
          })
        );
      });

      // Success message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/prompt updated successfully/i)
        ).toBeInTheDocument();
      });

      // Updated content is displayed
      expect(
        screen.getByText(/summarize the document with bullet points/i)
      ).toBeInTheDocument();
    });

    it("prevents editing public prompts", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Explain")).toBeInTheDocument();
      });

      // Find the "Explain" prompt (public prompt)
      const explainCard = screen
        .getByText("Explain")
        .closest("div[class*='border']");

      // Public prompts should not have edit button or it should be disabled
      const moreButton = within(explainCard!).queryByRole("button", {
        name: /edit|more/i,
      });

      if (moreButton) {
        await user.click(moreButton);

        // Edit option should not be available or should be disabled
        const editOption = screen.queryByText(/edit/i);
        if (editOption) {
          expect(editOption).toHaveAttribute("aria-disabled", "true");
        }
      }
    });

    it("shows error when update fails", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      const summarizeCard = screen
        .getByText("Summarize")
        .closest("div[class*='border']");

      const editButton = within(summarizeCard!).getByRole("button", {
        name: /edit|more/i,
      });
      await user.click(editButton);
      await user.click(screen.getByText(/edit/i));

      const contentInput = within(summarizeCard!).getByDisplayValue(
        /summarize the uploaded/i
      );
      await user.clear(contentInput);
      await user.type(contentInput, "New content");

      // Mock failed update
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: false,
        status: 500,
      });

      const saveButton = within(summarizeCard!).getByRole("button", {
        name: /save/i,
      });
      await user.click(saveButton);

      // Error message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/failed to update prompt/i)
        ).toBeInTheDocument();
      });
    });
  });

  describe("Delete: Removing Prompts", () => {
    it("allows user to delete a user-created prompt", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Translate")).toBeInTheDocument();
      });

      // User opens dropdown menu for "Translate" prompt
      const translateCard = screen
        .getByText("Translate")
        .closest("div[class*='border']");

      const moreButton = within(translateCard!).getByRole("button", {
        name: /more/i,
      });
      await user.click(moreButton);

      // Mock successful deletion
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => ({}),
      });

      // User clicks delete option
      const deleteOption = screen.getByText(/delete/i);
      await user.click(deleteOption);

      // API is called to delete prompt
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/input_prompt/3",
          expect.objectContaining({
            method: "DELETE",
          })
        );
      });

      // Success message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/prompt deleted successfully/i)
        ).toBeInTheDocument();
      });

      // Prompt is removed from list
      expect(screen.queryByText("Translate")).not.toBeInTheDocument();
    });

    it("hides public prompts instead of deleting them", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Explain")).toBeInTheDocument();
      });

      const explainCard = screen
        .getByText("Explain")
        .closest("div[class*='border']");

      const moreButton = within(explainCard!).getByRole("button", {
        name: /more/i,
      });
      await user.click(moreButton);

      // Mock successful hide operation
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => ({}),
      });

      // User clicks hide/delete option
      const hideOption = screen.getByText(/hide|delete/i);
      await user.click(hideOption);

      // API is called to hide (not delete) public prompt
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/input_prompt/2/hide",
          expect.objectContaining({
            method: "POST",
          })
        );
      });

      // Success message shows "hidden"
      await waitFor(() => {
        expect(
          screen.getByText(/prompt hidden successfully/i)
        ).toBeInTheDocument();
      });

      // Prompt is removed from list
      expect(screen.queryByText("Explain")).not.toBeInTheDocument();
    });

    it("shows error when deletion fails", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => mockPrompts,
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Translate")).toBeInTheDocument();
      });

      const translateCard = screen
        .getByText("Translate")
        .closest("div[class*='border']");

      const moreButton = within(translateCard!).getByRole("button", {
        name: /more/i,
      });
      await user.click(moreButton);

      // Mock failed deletion
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: false,
        status: 500,
      });

      await user.click(screen.getByText(/delete/i));

      // Error message is shown
      await waitFor(() => {
        expect(
          screen.getByText(/failed to delete.*hide prompt/i)
        ).toBeInTheDocument();
      });

      // Prompt still exists in list
      expect(screen.getByText("Translate")).toBeInTheDocument();
    });
  });

  describe("Complete User Workflow", () => {
    it("user can create, edit, and delete prompts in sequence", async () => {
      const user = userEvent.setup();

      // Initial fetch
      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => [mockPrompts[0]], // Start with one prompt
      });

      render(<InputPrompts />);

      await waitFor(() => {
        expect(screen.getByText("Summarize")).toBeInTheDocument();
      });

      // STEP 1: Create new prompt
      await user.click(screen.getByRole("button", { name: /add.*prompt/i }));
      await user.type(
        screen.getByPlaceholderText(/prompt shortcut/i),
        "Review"
      );
      await user.type(
        screen.getByPlaceholderText(/actual prompt/i),
        "Review this code for best practices."
      );

      const newPrompt = {
        id: 10,
        prompt: "Review",
        content: "Review this code for best practices.",
        is_public: false,
        active: true,
      };

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => newPrompt,
      });

      await user.click(screen.getByRole("button", { name: /create/i }));

      await waitFor(() => {
        expect(screen.getByText("Review")).toBeInTheDocument();
        expect(
          screen.getByText(/review this code for best practices/i)
        ).toBeInTheDocument();
      });

      // STEP 2: Edit the new prompt
      const reviewCard = screen
        .getByText("Review")
        .closest("div[class*='border']");

      const editButton = within(reviewCard!).getByRole("button", {
        name: /more/i,
      });
      await user.click(editButton);
      await user.click(screen.getByText(/edit/i));

      const contentInput = within(reviewCard!).getByDisplayValue(
        /review this code/i
      );
      await user.clear(contentInput);
      await user.type(
        contentInput,
        "Review this code for security vulnerabilities."
      );

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => ({}),
      });

      await user.click(
        within(reviewCard!).getByRole("button", { name: /save/i })
      );

      await waitFor(() => {
        expect(
          screen.getByText(/review this code for security vulnerabilities/i)
        ).toBeInTheDocument();
      });

      // STEP 3: Delete the prompt
      const moreButton = within(reviewCard!).getByRole("button", {
        name: /more/i,
      });
      await user.click(moreButton);

      fetchSpy.mockResolvedValueOnce({
        // @ts-ignore

        ok: true,
        json: async () => ({}),
      });

      await user.click(screen.getByText(/delete/i));

      await waitFor(() => {
        expect(screen.queryByText("Review")).not.toBeInTheDocument();
      });

      // Verify all API calls were made correctly
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt",
        expect.objectContaining({ method: "POST" })
      );
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt/10",
        expect.objectContaining({ method: "PATCH" })
      );
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt/10",
        expect.objectContaining({ method: "DELETE" })
      );
    });
  });
});
