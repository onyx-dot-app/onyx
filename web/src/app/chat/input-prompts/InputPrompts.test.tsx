/**
 * Integration Test: Input Prompts CRUD Workflow
 *
 * Tests the complete user journey for managing prompt shortcuts.
 * This tests the full workflow: fetch → create → edit → delete
 */
import React from "react";
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import InputPrompts from "./InputPrompts";

// Mock next/navigation for BackButton
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    back: jest.fn(),
    refresh: jest.fn(),
  }),
}));

describe("Input Prompts CRUD Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("fetches and displays existing prompts on load", async () => {
    // Mock GET /api/input_prompt to return existing prompts
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          prompt: "Summarize",
          content: "Summarize the uploaded document and highlight key points.",
          is_public: false,
        },
        {
          id: 2,
          prompt: "Explain",
          content: "Explain this concept in simple terms.",
          is_public: true,
        },
      ],
    } as Response);

    render(<InputPrompts />);

    // Verify API was called to fetch prompts
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    // Verify prompts are displayed
    await waitFor(() => {
      expect(screen.getByText("Summarize")).toBeInTheDocument();
      expect(screen.getByText("Explain")).toBeInTheDocument();
      expect(
        screen.getByText(
          /Summarize the uploaded document and highlight key points/i
        )
      ).toBeInTheDocument();
    });
  });

  test("creates a new prompt successfully", async () => {
    const user = userEvent.setup();

    // Mock GET to return empty prompts initially
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Mock POST /api/input_prompt for create
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 3,
        prompt: "Review",
        content: "Review this code for potential improvements.",
        is_public: false,
      }),
    } as Response);

    render(<InputPrompts />);

    // Wait for initial fetch to complete
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    // User clicks "Create New Prompt" button
    const createButton = screen.getByRole("button", {
      name: /create new prompt/i,
    });
    await user.click(createButton);

    // Verify create form is displayed
    expect(screen.getByPlaceholderText(/prompt shortcut/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/actual prompt/i)).toBeInTheDocument();

    // User fills out the form
    const shortcutInput = screen.getByPlaceholderText(/prompt shortcut/i);
    const promptInput = screen.getByPlaceholderText(/actual prompt/i);

    await user.type(shortcutInput, "Review");
    await user.type(
      promptInput,
      "Review this code for potential improvements."
    );

    // User clicks Create button
    const submitButton = screen.getByRole("button", { name: /^create$/i });
    await user.click(submitButton);

    // Verify POST request was made
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    // Verify request body
    const createCallArgs = fetchSpy.mock.calls[1]; // Second call (first was GET)
    const createBody = JSON.parse(createCallArgs[1].body);
    expect(createBody).toEqual({
      prompt: "Review",
      content: "Review this code for potential improvements.",
      is_public: false,
    });

    // Verify success message
    await waitFor(() => {
      expect(
        screen.getByText(/prompt created successfully/i)
      ).toBeInTheDocument();
    });

    // Verify new prompt is displayed
    expect(screen.getByText("Review")).toBeInTheDocument();
  });

  test("edits an existing user-created prompt", async () => {
    const user = userEvent.setup();

    // Mock GET to return a user-created prompt
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          prompt: "Summarize",
          content: "Summarize the document.",
          is_public: false,
        },
      ],
    } as Response);

    // Mock PATCH for update
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    // Wait for prompts to load
    await waitFor(() => {
      expect(screen.getByText("Summarize")).toBeInTheDocument();
    });

    // Click the dropdown menu (MoreVertical button)
    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    expect(moreButton).toBeDefined();
    await user.click(moreButton!);

    // Wait for Edit option to appear and click it
    const editOption = await screen.findByRole("menuitem", { name: /edit/i });
    await user.click(editOption);

    // Verify edit form is displayed with current values
    const textareas = screen.getAllByRole("textbox");
    expect(textareas[0]).toHaveValue("Summarize");
    expect(textareas[1]).toHaveValue("Summarize the document.");

    // User modifies the content
    await user.clear(textareas[1]);
    await user.type(
      textareas[1],
      "Summarize the document and provide key insights."
    );

    // User clicks Save
    const saveButton = screen.getByRole("button", { name: /save/i });
    await user.click(saveButton);

    // Verify PATCH request was made
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt/1",
        expect.objectContaining({
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    // Verify request body
    const patchCallArgs = fetchSpy.mock.calls[1];
    const patchBody = JSON.parse(patchCallArgs[1].body);
    expect(patchBody).toEqual({
      prompt: "Summarize",
      content: "Summarize the document and provide key insights.",
      active: true,
    });

    // Verify success message
    await waitFor(() => {
      expect(
        screen.getByText(/prompt updated successfully/i)
      ).toBeInTheDocument();
    });
  });

  test("deletes a user-created prompt", async () => {
    const user = userEvent.setup();

    // Mock GET to return a user-created prompt
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          prompt: "Summarize",
          content: "Summarize the document.",
          is_public: false,
        },
      ],
    } as Response);

    // Mock DELETE
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    // Wait for prompts to load
    await waitFor(() => {
      expect(screen.getByText("Summarize")).toBeInTheDocument();
    });

    // Click the dropdown menu
    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    await user.click(moreButton!);

    // Wait for Delete option to appear and click it
    const deleteOption = await screen.findByRole("menuitem", {
      name: /delete/i,
    });
    await user.click(deleteOption);

    // Verify DELETE request was made
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt/1", {
        method: "DELETE",
      });
    });

    // Verify success message
    await waitFor(() => {
      expect(
        screen.getByText(/prompt deleted successfully/i)
      ).toBeInTheDocument();
    });

    // Verify prompt is removed from display
    await waitFor(() => {
      expect(screen.queryByText("Summarize")).not.toBeInTheDocument();
    });
  });

  test("hides a public prompt instead of deleting it", async () => {
    const user = userEvent.setup();

    // Mock GET to return a public prompt
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 2,
          prompt: "Explain",
          content: "Explain this concept.",
          is_public: true,
        },
      ],
    } as Response);

    // Mock POST to hide endpoint
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    // Wait for prompts to load
    await waitFor(() => {
      expect(screen.getByText("Explain")).toBeInTheDocument();
    });

    // Verify "Built-in" chip is shown
    expect(screen.getByText("Built-in")).toBeInTheDocument();

    // Click the dropdown menu
    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    await user.click(moreButton!);

    // Wait for menu to open and verify Edit option is NOT shown for public prompts
    await waitFor(() => {
      expect(
        screen.getByRole("menuitem", { name: /delete/i })
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("menuitem", { name: /edit/i })
    ).not.toBeInTheDocument();

    // Click Delete option (which actually hides for public prompts)
    const deleteOption = screen.getByRole("menuitem", { name: /delete/i });
    await user.click(deleteOption);

    // Verify POST to hide endpoint was made
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt/2/hide", {
        method: "POST",
      });
    });

    // Verify success message says "hidden" not "deleted"
    await waitFor(() => {
      expect(
        screen.getByText(/prompt hidden successfully/i)
      ).toBeInTheDocument();
    });
  });

  test("shows error when fetch fails", async () => {
    // Mock failed GET request
    fetchSpy.mockRejectedValueOnce(new Error("Network error"));

    render(<InputPrompts />);

    // Verify error message is displayed
    await waitFor(() => {
      expect(
        screen.getByText(/failed to fetch prompt shortcuts/i)
      ).toBeInTheDocument();
    });
  });

  test("shows error when create fails", async () => {
    const user = userEvent.setup();

    // Mock GET to return empty prompts
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Mock failed POST
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 500,
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    // Open create form
    const createButton = screen.getByRole("button", {
      name: /create new prompt/i,
    });
    await user.click(createButton);

    // Fill form
    const shortcutInput = screen.getByPlaceholderText(/prompt shortcut/i);
    const promptInput = screen.getByPlaceholderText(/actual prompt/i);
    await user.type(shortcutInput, "Test");
    await user.type(promptInput, "Test content");

    // Submit
    const submitButton = screen.getByRole("button", { name: /^create$/i });
    await user.click(submitButton);

    // Verify error message
    await waitFor(() => {
      expect(screen.getByText(/failed to create prompt/i)).toBeInTheDocument();
    });
  });
});
