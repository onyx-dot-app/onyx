/**
 * Integration tests for MultiToolRenderer component
 * Tests UI rendering and user interactions with mocked RendererComponent
 */

import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
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

  afterEach(() => {
    jest.runOnlyPendingTimers();
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

    expect(screen.getByText("Tool executing")).toBeInTheDocument();
  });

  test("clicking tool status expands to show all tools in streaming", async () => {
    const user = setupUser();
    renderMultiToolRenderer({
      toolCount: 3,
      isComplete: false,
    });

    // Find the tool status
    const toolStatus = screen.getByText("Tool executing");

    // Click to expand
    await user.click(toolStatus);

    // More tools should be visible
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

    // Should show tool executing status
    expect(screen.getByText("Tool executing")).toBeInTheDocument();

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

  test("shows Done node only when allToolsDisplayed=true", async () => {
    const user = setupUser();

    // Without final answer coming
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

    // Done should not appear
    expect(screen.queryByText("Done")).not.toBeInTheDocument();

    // Now with final answer coming
    rerender(
      <MultiToolRenderer
        packetGroups={createToolGroups(2)}
        chatState={createMockChatState()}
        isComplete={true}
        isFinalAnswerComing={true}
        stopPacketSeen={true}
      />
    );

    // Done should appear
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
    const emptyGroups: { turn_index: number; packets: any[] }[] = [];

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
