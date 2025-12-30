/**
 * Integration tests for MultiToolRenderer component
 * Tests UI rendering and user interactions with mocked RendererComponent
 */

import React from "react";
import {
  act,
  render,
  screen,
  waitFor,
  setupUser,
} from "@tests/setup/test-utils";
import MultiToolRenderer from "./MultiToolRenderer";
import {
  createToolGroups,
  createMockChatState,
  renderMultiToolRenderer,
  createInternalSearchToolGroup,
} from "@tests/setup/multiToolTestHelpers";

// The search tool renderers use ResultIcon, which pulls in complex source metadata.
// For these tests we only care about statuses/text, so mock it to avoid heavy deps.
jest.mock("@/components/chat/sources/SourceCard", () => ({
  ResultIcon: () => <div data-testid="result-icon" />,
}));

// Mock the RendererComponent to return predictable, simple output
jest.mock("./renderMessageComponent", () => ({
  RendererComponent: ({ children, onComplete }: any) => {
    // Simulate completion immediately (no animations)
    React.useEffect(() => {
      const timer = setTimeout(() => onComplete(), 0);
      return () => clearTimeout(timer);
    }, [onComplete]);

    // Return simple, testable output
    return children({
      icon: () => <div data-testid="tool-icon">🔧</div>,
      status: "Tool executing",
      content: <div data-testid="tool-content">Tool content</div>,
      expandedText: <div data-testid="tool-expanded">Expanded content</div>,
    });
  },
}));

describe("MultiToolRenderer - Complete Mode", () => {
  test("shows summary with correct step count", () => {
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    expect(screen.getByText("3 steps")).toBeInTheDocument();
  });

  test('shows "steps" even for single tool', () => {
    renderMultiToolRenderer({
      toolCount: 1,
      isComplete: true,
    });

    // Component shows "X steps" regardless of count
    expect(screen.getByText("1 steps")).toBeInTheDocument();
  });

  test("expands to show all tools when clicked", async () => {
    const user = setupUser();
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    // Click summary to expand
    await user.click(screen.getByText("3 steps"));

    // Check that expanded tools are displayed
    await waitFor(() => {
      const expandedContents = screen.getAllByTestId("tool-expanded");
      expect(expandedContents.length).toBe(3);
    });
  });

  test("shows Done node after all tools displayed", async () => {
    const user = setupUser();
    renderMultiToolRenderer({
      toolCount: 2,
      isComplete: true,
      isFinalAnswerComing: true,
    });

    // Expand
    await user.click(screen.getByText("2 steps"));

    // Wait for Done node
    await waitFor(() => {
      expect(screen.getByText("Done")).toBeInTheDocument();
    });
  });

  test("internal search tool is split into two steps in summary", () => {
    const searchGroup = createInternalSearchToolGroup(0);

    render(
      <MultiToolRenderer
        packetGroups={[searchGroup]}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={false}
        stopPacketSeen={true}
      />
    );

    // One internal search tool becomes two logical steps
    expect(screen.getByText("2 steps")).toBeInTheDocument();
  });

  test("internal search tool shows separate Searching and Reading steps when expanded", async () => {
    const user = setupUser();

    const searchGroup = createInternalSearchToolGroup(0);

    render(
      <MultiToolRenderer
        packetGroups={[searchGroup]}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Summary should reflect two steps
    await user.click(screen.getByText("2 steps"));

    await waitFor(() => {
      // Step 1 status from SearchToolStep1Renderer
      expect(screen.getByText("Searching internally")).toBeInTheDocument();
      // Step 2 status from SearchToolStep2Renderer
      expect(screen.getByText("Reading")).toBeInTheDocument();
    });
  });

  test("collapses when clicking summary again", async () => {
    const user = setupUser();
    const { container } = renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    // Expand
    await user.click(screen.getByText("3 steps"));

    await waitFor(() => {
      const expandedContents = screen.getAllByTestId("tool-expanded");
      expect(expandedContents.length).toBe(3);
    });

    // Collapse
    await user.click(screen.getByText("3 steps"));

    // Verify the container has the collapsed classes (max-h-0 opacity-0)
    await waitFor(() => {
      const expandedContainer = container.querySelector(
        'div[class*="max-h-0"]'
      );
      expect(expandedContainer).toBeInTheDocument();
      expect(expandedContainer).toHaveClass("opacity-0");
    });
  });

  test("chevron icon rotates based on expanded state", async () => {
    const user = setupUser();
    const { container } = renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    // Initially collapsed - chevron should have rotation class
    const chevronInitial = container.querySelector("svg");
    expect(chevronInitial).toBeInTheDocument();
    expect(chevronInitial).toHaveClass("rotate-[-90deg]");

    // Click to expand
    await user.click(screen.getByText("3 steps"));

    // Chevron should be in expanded state (no rotation)
    const chevronExpanded = container.querySelector("svg");
    expect(chevronExpanded).toBeInTheDocument();
    expect(chevronExpanded).not.toHaveClass("rotate-[-90deg]");

    // Click to collapse
    await user.click(screen.getByText("3 steps"));

    // Chevron should rotate back (have rotation class again)
    const chevronCollapsed = container.querySelector("svg");
    expect(chevronCollapsed).toBeInTheDocument();
    expect(chevronCollapsed).toHaveClass("rotate-[-90deg]");
  });
});

describe("MultiToolRenderer - Streaming Mode", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(async () => {
    // Wrap timer execution in act() since it triggers React state updates
    await act(async () => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  test("shows tool content when tools are streaming", () => {
    const toolGroups = createToolGroups(3);

    render(
      <MultiToolRenderer
        packetGroups={toolGroups}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
      />
    );

    // Should show some tool content
    const toolContents = screen.queryAllByTestId("tool-content");
    expect(toolContents.length).toBeGreaterThan(0);
  });

  test("shows Tool executing status in streaming mode", () => {
    renderMultiToolRenderer({
      toolCount: 2,
      isComplete: false,
    });

    // With all tools shown, there will be multiple "Tool executing" texts
    const statuses = screen.getAllByText("Tool executing");
    expect(statuses.length).toBeGreaterThan(0);
  });

  test("clicking tool status expands to show all tools in streaming", async () => {
    const user = setupUser();
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: false,
    });

    // Find a tool status (there will be multiple since all tools are shown)
    const toolStatuses = screen.getAllByText("Tool executing");
    expect(toolStatuses.length).toBeGreaterThan(0);

    // Click to expand
    await user.click(toolStatuses[0]!);

    // Tools should be visible
    await waitFor(() => {
      const toolContents = screen.getAllByTestId("tool-content");
      expect(toolContents.length).toBeGreaterThanOrEqual(1);
    });
  });

  test("shows tool content progressively in streaming mode", async () => {
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: false,
    });

    // Should show tool executing status (multiple expected since all tools shown)
    const statuses = screen.getAllByText("Tool executing");
    expect(statuses.length).toBeGreaterThan(0);

    // Tool content should be visible
    const toolContents = screen.getAllByTestId("tool-content");
    expect(toolContents.length).toBeGreaterThanOrEqual(1);
  });

  test("shows border and styling for streaming tools", () => {
    const { container } = renderMultiToolRenderer({
      toolCount: 2,
      isComplete: false,
    });

    // Should have the streaming container with border
    const streamingContainer = container.querySelector(".border-border-medium");
    expect(streamingContainer).toBeInTheDocument();
  });
});

describe("MultiToolRenderer - State Transitions", () => {
  test("calls onAllToolsDisplayed callback at correct time", async () => {
    const onAllToolsDisplayed = jest.fn();

    render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
        onAllToolsDisplayed={onAllToolsDisplayed}
      />
    );

    await waitFor(() => {
      expect(onAllToolsDisplayed).toHaveBeenCalledTimes(1);
    });
  });

  test("does not call onAllToolsDisplayed when not complete", () => {
    const onAllToolsDisplayed = jest.fn();

    render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
        onAllToolsDisplayed={onAllToolsDisplayed}
      />
    );

    // Should not be called immediately
    expect(onAllToolsDisplayed).not.toHaveBeenCalled();
  });

  test("shows Done node when allToolsDisplayed=true", async () => {
    const user = setupUser();

    // With isComplete=true, all tools are visible and completed, so Done should appear
    // Note: allToolsDisplayed is now independent of isFinalAnswerComing to avoid
    // circular dependency (parent uses onAllToolsDisplayed to set finalAnswerComing)
    const { rerender } = render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={false}
        stopPacketSeen={true}
      />
    );

    // Expand
    await user.click(screen.getByText("2 steps"));

    // Done should appear because all tools are complete (regardless of isFinalAnswerComing)
    await waitFor(() => {
      expect(screen.getByText("Done")).toBeInTheDocument();
    });

    // Remains visible after setting final answer coming
    rerender(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Done should still appear
    await waitFor(() => {
      expect(screen.getByText("Done")).toBeInTheDocument();
    });
  });
});

describe("MultiToolRenderer - Edge Cases", () => {
  test("renders nothing when no tools", () => {
    const { container } = renderMultiToolRenderer({ toolCount: 0 });
    expect(container.firstChild).toBeNull();
  });

  test("handles single tool with collapse UI", () => {
    renderMultiToolRenderer({
      toolCount: 1,
      isComplete: true,
    });

    // Should show "1 steps" (component uses plural for all counts)
    expect(screen.getByText("1 steps")).toBeInTheDocument();
  });

  test("handles single tool in streaming mode", () => {
    renderMultiToolRenderer({
      toolCount: 1,
      isComplete: false,
    });

    // Should show tool executing
    expect(screen.getByText("Tool executing")).toBeInTheDocument();
  });

  test("filters tool packets correctly", () => {
    const toolGroups = createToolGroups(3);

    render(
      <MultiToolRenderer
        packetGroups={toolGroups}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Should process 3 tools
    expect(screen.getByText("3 steps")).toBeInTheDocument();
  });

  test("handles empty packet groups gracefully", () => {
    const emptyGroups: {
      turn_index: number;
      tab_index: number;
      packets: any[];
    }[] = [];

    const { container } = render(
      <MultiToolRenderer
        packetGroups={emptyGroups}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
      />
    );

    expect(container.firstChild).toBeNull();
  });
});

describe("MultiToolRenderer - Accessibility", () => {
  test("summary is clickable for keyboard users", async () => {
    const user = setupUser();
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    const summary = screen.getByText("3 steps");

    // Should be clickable
    await user.click(summary);

    await waitFor(() => {
      const expandedContents = screen.getAllByTestId("tool-expanded");
      expect(expandedContents.length).toBe(3);
    });
  });

  test("renders with proper structure for screen readers", () => {
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: true,
    });

    // Summary text should be present
    expect(screen.getByText("3 steps")).toBeInTheDocument();
  });
});

describe("MultiToolRenderer - Parallel Tools", () => {
  test("renders parallel tools as tabs when multiple tools share same turn_index", () => {
    // Create parallel tools: internal search and web search at same turn_index
    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: {
              type: "search_tool_start",
              is_internet_search: false,
            },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: {
              type: "search_tool_queries_delta",
              queries: ["test query"],
            },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: {
              type: "search_tool_documents_delta",
              documents: [
                { document_id: "doc-1", semantic_identifier: "Doc 1" },
              ],
            },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: {
              type: "section_end",
            },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: {
              type: "search_tool_start",
              is_internet_search: true,
            },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: {
              type: "search_tool_queries_delta",
              queries: ["web query"],
            },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: {
              type: "search_tool_documents_delta",
              documents: [
                { document_id: "doc-2", semantic_identifier: "Doc 2" },
              ],
            },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: {
              type: "section_end",
            },
          },
        ],
      },
    ];

    render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Should show both tools as tabs
    expect(screen.getByText("Internal Search")).toBeInTheDocument();
    expect(screen.getByText("Web Search")).toBeInTheDocument();
  });

  test("shows navigation arrows for parallel tools", () => {
    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_start", is_internet_search: false },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "section_end" },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "search_tool_start", is_internet_search: true },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "section_end" },
          },
        ],
      },
    ];

    const { container } = render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Should have navigation arrows
    const chevronLeftButtons = container.querySelectorAll("svg.w-4.h-4");
    expect(chevronLeftButtons.length).toBeGreaterThan(0);
  });

  test("allows switching between tabs", async () => {
    const user = setupUser();

    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_start", is_internet_search: false },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "section_end" },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "search_tool_start", is_internet_search: true },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "section_end" },
          },
        ],
      },
    ];

    render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Click on Web Search tab
    await user.click(screen.getByText("Web Search"));

    // Web Search tab should now be active (has different styling)
    const webSearchButton = screen.getByText("Web Search").closest("button");
    expect(webSearchButton).toHaveClass("bg-neutral-800");
  });

  test("shows expand/collapse button for parallel tools", async () => {
    const user = setupUser();

    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_start", is_internet_search: false },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_queries_delta", queries: ["test"] },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "section_end" },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "search_tool_start", is_internet_search: true },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "section_end" },
          },
        ],
      },
    ];

    const { container } = render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Should have expand/collapse toggle
    const toggleButtons = container.querySelectorAll("button");
    expect(toggleButtons.length).toBeGreaterThan(0);
  });

  test("arrow buttons navigate between tabs", async () => {
    const user = setupUser();

    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_start", is_internet_search: false },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "section_end" },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "search_tool_start", is_internet_search: true },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "section_end" },
          },
        ],
      },
    ];

    const { container } = render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Initially, Internal Search should be active
    const internalSearchButton = screen
      .getByText("Internal Search")
      .closest("button");
    expect(internalSearchButton).toHaveClass("bg-neutral-800");

    // Find the next tab button (right arrow) using aria-label
    const nextButton = container.querySelector('button[aria-label="Next tab"]');
    expect(nextButton).toBeInTheDocument();
    expect(nextButton).not.toBeDisabled();

    // Click next to go to Web Search
    await user.click(nextButton!);

    // Now Web Search should be active
    const webSearchButton = screen.getByText("Web Search").closest("button");
    expect(webSearchButton).toHaveClass("bg-neutral-800");

    // Internal Search should no longer be active
    expect(internalSearchButton).not.toHaveClass("bg-neutral-800");

    // Previous button should now be enabled
    const prevButton = container.querySelector(
      'button[aria-label="Previous tab"]'
    );
    expect(prevButton).not.toBeDisabled();

    // Click previous to go back to Internal Search
    await user.click(prevButton!);

    // Internal Search should be active again
    expect(internalSearchButton).toHaveClass("bg-neutral-800");
  });

  test("arrow buttons are disabled at boundaries", () => {
    const parallelGroups = [
      {
        turn_index: 0,
        tab_index: 0,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "search_tool_start", is_internet_search: false },
          },
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "section_end" },
          },
        ],
      },
      {
        turn_index: 0,
        tab_index: 1,
        packets: [
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "search_tool_start", is_internet_search: true },
          },
          {
            placement: { turn_index: 0, tab_index: 1 },
            obj: { type: "section_end" },
          },
        ],
      },
    ];

    const { container } = render(
      <MultiToolRenderer
        packetGroups={parallelGroups as any}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // At the first tab, previous should be disabled
    const prevButton = container.querySelector(
      'button[aria-label="Previous tab"]'
    );
    expect(prevButton).toBeDisabled();

    // Next should be enabled since there's another tab
    const nextButton = container.querySelector('button[aria-label="Next tab"]');
    expect(nextButton).not.toBeDisabled();
  });
});

describe("MultiToolRenderer - Shimmering", () => {
  test("stops shimmering when isStreaming is false", () => {
    const { container } = render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
        isStreaming={false}
      />
    );

    // When isStreaming is false, loading-text class should not be applied
    const loadingElements = container.querySelectorAll(".loading-text");
    expect(loadingElements.length).toBe(0);
  });

  test("applies shimmer classes when streaming", () => {
    const { container } = render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
        isStreaming={true}
      />
    );

    // When isStreaming is true, loading-text class should be applied
    const loadingElements = container.querySelectorAll(".loading-text");
    expect(loadingElements.length).toBeGreaterThan(0);
  });

  test("stops shimmering when stopPacketSeen is true", () => {
    const { container } = render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={false}
        isFinalAnswerComing={false}
        stopPacketSeen={true}
        isStreaming={true}
      />
    );

    // When stopPacketSeen is true, shimmering should stop regardless of isStreaming
    const loadingElements = container.querySelectorAll(".loading-text");
    expect(loadingElements.length).toBe(0);
  });

  test("stops shimmering when isComplete is true", () => {
    const { container } = render(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={false}
        stopPacketSeen={false}
        isStreaming={true}
      />
    );

    // When isComplete is true, shimmering should stop
    const loadingElements = container.querySelectorAll(".loading-text");
    expect(loadingElements.length).toBe(0);
  });
});
