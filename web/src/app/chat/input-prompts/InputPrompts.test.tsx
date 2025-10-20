/**
 * Integration Test: Input Prompts CRUD Workflow
 *
 * Tests the complete user journey for managing prompt shortcuts.
 * This tests the full workflow: fetch → create → edit → delete
 */
import React from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
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
    // Mock GET /api/input_prompt
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

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

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
    const user = setupUser();

    // Mock GET /api/input_prompt
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Mock POST /api/input_prompt
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

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    const createButton = screen.getByRole("button", {
      name: /create new prompt/i,
    });
    await user.click(createButton);

    expect(
      await screen.findByPlaceholderText(/prompt shortcut/i)
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/actual prompt/i)).toBeInTheDocument();

    const shortcutInput = screen.getByPlaceholderText(/prompt shortcut/i);
    const promptInput = screen.getByPlaceholderText(/actual prompt/i);

    await user.type(shortcutInput, "Review");
    await user.type(
      promptInput,
      "Review this code for potential improvements."
    );

    const submitButton = screen.getByRole("button", { name: /^create$/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    const createCallArgs = fetchSpy.mock.calls[1]; // Second call (first was GET)
    const createBody = JSON.parse(createCallArgs[1].body);
    expect(createBody).toEqual({
      prompt: "Review",
      content: "Review this code for potential improvements.",
      is_public: false,
    });

    await waitFor(() => {
      expect(
        screen.getByText(/prompt created successfully/i)
      ).toBeInTheDocument();
    });

    expect(await screen.findByText("Review")).toBeInTheDocument();
  });

  test("edits an existing user-created prompt", async () => {
    const user = setupUser();

    // Mock GET /api/input_prompt
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

    // Mock PATCH /api/input_prompt/1
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(screen.getByText("Summarize")).toBeInTheDocument();
    });

    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    expect(moreButton).toBeDefined();
    await user.click(moreButton!);

    const editOption = await screen.findByRole("menuitem", { name: /edit/i });
    await user.click(editOption);

    let textareas: HTMLElement[];
    await waitFor(() => {
      textareas = screen.getAllByRole("textbox");
      expect(textareas[0]).toHaveValue("Summarize");
      expect(textareas[1]).toHaveValue("Summarize the document.");
    });

    await user.clear(textareas![1]);
    await user.type(
      textareas![1],
      "Summarize the document and provide key insights."
    );

    const saveButton = screen.getByRole("button", { name: /save/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/input_prompt/1",
        expect.objectContaining({
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    const patchCallArgs = fetchSpy.mock.calls[1];
    const patchBody = JSON.parse(patchCallArgs[1].body);
    expect(patchBody).toEqual({
      prompt: "Summarize",
      content: "Summarize the document and provide key insights.",
      active: true,
    });

    await waitFor(() => {
      expect(
        screen.getByText(/prompt updated successfully/i)
      ).toBeInTheDocument();
    });
  });

  test("deletes a user-created prompt", async () => {
    const user = setupUser();

    // Mock GET /api/input_prompt
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

    // Mock DELETE /api/input_prompt/1
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(screen.getByText("Summarize")).toBeInTheDocument();
    });

    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    await user.click(moreButton!);

    const deleteOption = await screen.findByRole("menuitem", {
      name: /delete/i,
    });
    await user.click(deleteOption);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt/1", {
        method: "DELETE",
      });
    });

    await waitFor(() => {
      expect(
        screen.getByText(/prompt deleted successfully/i)
      ).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.queryByText("Summarize")).not.toBeInTheDocument();
    });
  });

  test("hides a public prompt instead of deleting it", async () => {
    const user = setupUser();

    // Mock GET /api/input_prompt
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

    // Mock POST /api/input_prompt/2/hide
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(screen.getByText("Explain")).toBeInTheDocument();
      expect(screen.getByText("Built-in")).toBeInTheDocument();
    });

    const dropdownButtons = screen.getAllByRole("button");
    const moreButton = dropdownButtons.find(
      (btn) => btn.textContent === "" && btn.querySelector("svg")
    );
    await user.click(moreButton!);

    // Edit option should NOT be shown for public prompts
    await waitFor(() => {
      expect(
        screen.getByRole("menuitem", { name: /delete/i })
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("menuitem", { name: /edit/i })
    ).not.toBeInTheDocument();

    // Public prompts use the hide endpoint instead of delete
    const deleteOption = screen.getByRole("menuitem", { name: /delete/i });
    await user.click(deleteOption);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt/2/hide", {
        method: "POST",
      });
    });

    await waitFor(() => {
      expect(
        screen.getByText(/prompt hidden successfully/i)
      ).toBeInTheDocument();
    });
  });

  test("shows error when fetch fails", async () => {
    // Mock GET /api/input_prompt (failure)
    fetchSpy.mockRejectedValueOnce(new Error("Network error"));

    render(<InputPrompts />);

    await waitFor(() => {
      expect(
        screen.getByText(/failed to fetch prompt shortcuts/i)
      ).toBeInTheDocument();
    });
  });

  test("shows error when create fails", async () => {
    const user = setupUser();

    // Mock GET /api/input_prompt
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Mock POST /api/input_prompt (failure)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 500,
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    const createButton = screen.getByRole("button", {
      name: /create new prompt/i,
    });
    await user.click(createButton);

    const shortcutInput =
      await screen.findByPlaceholderText(/prompt shortcut/i);
    const promptInput = screen.getByPlaceholderText(/actual prompt/i);
    await user.type(shortcutInput, "Test");
    await user.type(promptInput, "Test content");

    const submitButton = screen.getByRole("button", { name: /^create$/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/failed to create prompt/i)).toBeInTheDocument();
    });
  });
});
