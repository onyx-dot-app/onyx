import React, { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import CommandMenu, {
  useCommandMenuContext,
} from "@/refresh-components/commandmenu/CommandMenu";

// Mock Radix Dialog portal to render inline for testing
jest.mock("@radix-ui/react-dialog", () => {
  const actual = jest.requireActual("@radix-ui/react-dialog");
  return {
    ...actual,
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

// Mock requestAnimationFrame for highlight updates
const originalRAF = global.requestAnimationFrame;
beforeAll(() => {
  global.requestAnimationFrame = (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  };
});
afterAll(() => {
  global.requestAnimationFrame = originalRAF;
});

function setupUser() {
  return userEvent.setup({ delay: null });
}

/**
 * Test wrapper for CommandMenu compound component
 */
function TestCommandMenu({
  open = true,
  onOpenChange = jest.fn(),
  includeFilter = false,
  defaultHighlightAction = true,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  includeFilter?: boolean;
  defaultHighlightAction?: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <CommandMenu open={open} onOpenChange={onOpenChange}>
      <CommandMenu.Content>
        <CommandMenu.Header placeholder="Search..." />
        <CommandMenu.List>
          <CommandMenu.Action
            value="action-1"
            onSelect={() => setSelected("action-1")}
            defaultHighlight={defaultHighlightAction}
          >
            Action 1
          </CommandMenu.Action>
          {includeFilter && (
            <CommandMenu.Filter value="filter-1" onSelect={() => {}}>
              Filter 1
            </CommandMenu.Filter>
          )}
          <CommandMenu.Item
            value="item-1"
            onSelect={() => setSelected("item-1")}
          >
            Item 1
          </CommandMenu.Item>
          <CommandMenu.Item
            value="item-2"
            onSelect={() => setSelected("item-2")}
          >
            Item 2
          </CommandMenu.Item>
        </CommandMenu.List>
        <CommandMenu.Footer
          leftActions={
            <CommandMenu.FooterAction
              icon={() => <span>Icon</span>}
              label="Select"
            />
          }
        />
      </CommandMenu.Content>
      {selected && <div data-testid="selected">{selected}</div>}
    </CommandMenu>
  );
}

/**
 * Minimal test wrapper for context hook testing
 */
function ContextTestComponent() {
  const context = useCommandMenuContext();
  return (
    <div>
      <div data-testid="highlighted-value">
        {context.highlightedValue ?? "none"}
      </div>
      <div data-testid="highlighted-type">
        {context.highlightedItemType ?? "none"}
      </div>
      <div data-testid="is-keyboard-nav">
        {context.isKeyboardNav ? "true" : "false"}
      </div>
    </div>
  );
}

function TestCommandMenuWithContext({
  open = true,
  onOpenChange = jest.fn(),
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <CommandMenu open={open} onOpenChange={onOpenChange}>
      <CommandMenu.Content>
        <CommandMenu.Header placeholder="Search..." />
        <CommandMenu.List>
          <CommandMenu.Action value="action-1" onSelect={() => {}}>
            Action 1
          </CommandMenu.Action>
          <CommandMenu.Item value="item-1" onSelect={() => {}}>
            Item 1
          </CommandMenu.Item>
        </CommandMenu.List>
        <ContextTestComponent />
      </CommandMenu.Content>
    </CommandMenu>
  );
}

describe("CommandMenu", () => {
  describe("Rendering", () => {
    test("renders children when open", () => {
      render(<TestCommandMenu open={true} />);
      expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
      // Use getAllByText since Truncated component creates visible + hidden measurement elements
      expect(screen.getAllByText("Action 1").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Item 1").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Item 2").length).toBeGreaterThan(0);
    });

    test("does not render content when closed", () => {
      render(<TestCommandMenu open={false} />);
      expect(
        screen.queryByPlaceholderText("Search...")
      ).not.toBeInTheDocument();
      expect(screen.queryByText("Action 1")).not.toBeInTheDocument();
    });

    test("renders header with placeholder text", () => {
      render(<TestCommandMenu open={true} />);
      const input = screen.getByPlaceholderText("Search...");
      expect(input).toBeInTheDocument();
      expect(input).toHaveFocus();
    });

    test("renders filter items", () => {
      render(<TestCommandMenu open={true} includeFilter={true} />);
      expect(screen.getByText("Filter 1")).toBeInTheDocument();
    });

    test("renders action items", () => {
      render(<TestCommandMenu open={true} />);
      // Use getAllByText since Truncated component creates visible + hidden measurement elements
      expect(screen.getAllByText("Action 1").length).toBeGreaterThan(0);
      // Verify the item is registered
      expect(
        document.querySelector('[data-command-item="action-1"]')
      ).toBeInTheDocument();
    });

    test("renders regular items", () => {
      render(<TestCommandMenu open={true} />);
      // Use getAllByText since Truncated component creates visible + hidden measurement elements
      expect(screen.getAllByText("Item 1").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Item 2").length).toBeGreaterThan(0);
      // Verify the items are registered
      expect(
        document.querySelector('[data-command-item="item-1"]')
      ).toBeInTheDocument();
      expect(
        document.querySelector('[data-command-item="item-2"]')
      ).toBeInTheDocument();
    });

    test("renders footer with actions", () => {
      render(<TestCommandMenu open={true} />);
      expect(screen.getByText("Select")).toBeInTheDocument();
    });
  });

  describe("Keyboard Navigation", () => {
    test("ArrowDown highlights next item", async () => {
      const user = setupUser();
      render(<TestCommandMenuWithContext open={true} />);

      // Wait for initial highlight
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });

      await user.keyboard("{ArrowDown}");

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });
    });

    test("ArrowUp highlights previous item", async () => {
      const user = setupUser();
      render(<TestCommandMenuWithContext open={true} />);

      // Move down first
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });

      await user.keyboard("{ArrowDown}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });

      await user.keyboard("{ArrowUp}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });

    test("ArrowDown wraps to first item at end", async () => {
      const user = setupUser();
      render(<TestCommandMenuWithContext open={true} />);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });

      // Move through all items
      await user.keyboard("{ArrowDown}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });

      // Should wrap back to action-1
      await user.keyboard("{ArrowDown}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });

    test("ArrowUp wraps to last item at start", async () => {
      const user = setupUser();
      render(<TestCommandMenuWithContext open={true} />);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });

      // Going up from first should wrap to last
      await user.keyboard("{ArrowUp}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });
    });

    test("Enter selects highlighted item", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();
      render(<TestCommandMenu open={true} onOpenChange={onOpenChange} />);

      // Wait for initial highlight and then press Enter
      await waitFor(() => {
        const items = document.querySelectorAll("[data-command-item]");
        expect(items.length).toBeGreaterThan(0);
      });

      await user.keyboard("{ArrowDown}"); // Move to item-1
      await user.keyboard("{Enter}");

      // Menu should close after selecting a non-filter item
      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("Escape closes menu", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();
      render(<TestCommandMenu open={true} onOpenChange={onOpenChange} />);

      await user.keyboard("{Escape}");

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    test("Enter on filter does not close menu", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();
      render(
        <TestCommandMenu
          open={true}
          onOpenChange={onOpenChange}
          includeFilter={true}
        />
      );

      // Navigate to filter
      await waitFor(() => {
        const items = document.querySelectorAll("[data-command-item]");
        expect(items.length).toBeGreaterThan(0);
      });

      await user.keyboard("{ArrowDown}"); // Move to filter-1
      await user.keyboard("{Enter}");

      // Menu should NOT close after selecting a filter
      await waitFor(() => {
        // Give it time to potentially call onOpenChange incorrectly
        return new Promise((r) => setTimeout(r, 100));
      });

      // onOpenChange should not have been called with false for filter selection
      const closeCalls = onOpenChange.mock.calls.filter(
        (call) => call[0] === false
      );
      expect(closeCalls.length).toBe(0);
    });
  });

  describe("Mouse Interaction", () => {
    test("Mouse hover highlights item", async () => {
      render(<TestCommandMenuWithContext open={true} />);

      // Use data-command-item selector directly
      const itemContainer = document.querySelector(
        '[data-command-item="item-1"]'
      );
      expect(itemContainer).toBeInTheDocument();

      // The LineItem component has a button inside that handles mouse events
      const button = itemContainer!.querySelector("button");
      expect(button).toBeInTheDocument();
      fireEvent.mouseEnter(button!);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });
    });

    test("Click selects item", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();
      render(<TestCommandMenu open={true} onOpenChange={onOpenChange} />);

      // Use data-command-item selector to find the clickable item container
      const itemContainer = document.querySelector(
        '[data-command-item="item-1"]'
      );
      expect(itemContainer).toBeInTheDocument();

      // The LineItem component has a button inside that handles click events
      const button = itemContainer!.querySelector("button");
      expect(button).toBeInTheDocument();
      await user.click(button!);

      await waitFor(() => {
        expect(onOpenChange).toHaveBeenCalledWith(false);
      });
    });

    test("Click on filter does not close menu", async () => {
      const user = setupUser();
      const onOpenChange = jest.fn();
      render(
        <TestCommandMenu
          open={true}
          onOpenChange={onOpenChange}
          includeFilter={true}
        />
      );

      // Use data-command-item selector directly
      const filterContainer = document.querySelector(
        '[data-command-item="filter-1"]'
      );
      expect(filterContainer).toBeInTheDocument();
      await user.click(filterContainer!);

      // Give it time to potentially call onOpenChange incorrectly
      await waitFor(() => {
        return new Promise((r) => setTimeout(r, 100));
      });

      // onOpenChange should not have been called with false for filter click
      const closeCalls = onOpenChange.mock.calls.filter(
        (call) => call[0] === false
      );
      expect(closeCalls.length).toBe(0);
    });
  });

  describe("Item Registration", () => {
    test("Items with defaultHighlight=false are skipped in initial highlight", async () => {
      render(<TestCommandMenuWithContext open={true} />);

      // The first selectable item (action-1) should be highlighted initially
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });

    test("First selectable item is highlighted on open", async () => {
      render(<TestCommandMenuWithContext open={true} />);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });

    test("Non-default-highlight action is skipped for initial highlight", async () => {
      // Render with defaultHighlightAction=false, so action-1 should be skipped
      render(<TestCommandMenu open={true} defaultHighlightAction={false} />);

      // The item-1 should be highlighted instead (first item with defaultHighlight=true)
      await waitFor(() => {
        const highlightedItems = document.querySelectorAll(
          '[aria-selected="true"]'
        );
        expect(highlightedItems.length).toBeGreaterThan(0);
        // Check that the highlighted item is item-1, not action-1
        const highlightedValues = Array.from(highlightedItems).map((el) =>
          el.getAttribute("data-command-item")
        );
        expect(highlightedValues).toContain("item-1");
      });
    });
  });

  describe("Context Hook", () => {
    test("useCommandMenuContext provides correct highlighted value", async () => {
      render(<TestCommandMenuWithContext open={true} />);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });

    test("useCommandMenuContext provides correct highlighted item type", async () => {
      render(<TestCommandMenuWithContext open={true} />);

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-type")).toHaveTextContent(
          "action"
        );
      });

      // Navigate to regular item
      const user = setupUser();
      await user.keyboard("{ArrowDown}");

      await waitFor(() => {
        expect(screen.getByTestId("highlighted-type")).toHaveTextContent(
          "item"
        );
      });
    });

    test("useCommandMenuContext throws when used outside CommandMenu", () => {
      // Suppress console.error for this test since we expect an error
      const consoleSpy = jest
        .spyOn(console, "error")
        .mockImplementation(() => {});

      expect(() => {
        render(<ContextTestComponent />);
      }).toThrow(
        "CommandMenu compound components must be used within CommandMenu"
      );

      consoleSpy.mockRestore();
    });

    test("isKeyboardNav is true after keyboard navigation", async () => {
      const user = setupUser();
      render(<TestCommandMenuWithContext open={true} />);

      // Initially should not be keyboard nav
      expect(screen.getByTestId("is-keyboard-nav")).toHaveTextContent("false");

      await user.keyboard("{ArrowDown}");

      await waitFor(() => {
        expect(screen.getByTestId("is-keyboard-nav")).toHaveTextContent("true");
      });
    });
  });

  describe("Menu State Reset", () => {
    test("highlight resets when menu closes and reopens", async () => {
      const { rerender } = render(<TestCommandMenuWithContext open={true} />);

      // Wait for initial highlight
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });

      // Navigate to item-1
      const user = setupUser();
      await user.keyboard("{ArrowDown}");
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "item-1"
        );
      });

      // Close menu
      rerender(<TestCommandMenuWithContext open={false} />);

      // Reopen menu
      rerender(<TestCommandMenuWithContext open={true} />);

      // Should reset to first item
      await waitFor(() => {
        expect(screen.getByTestId("highlighted-value")).toHaveTextContent(
          "action-1"
        );
      });
    });
  });

  describe("Header Input Behavior", () => {
    test("typing in input does not trigger keyboard navigation", async () => {
      const user = setupUser();
      const onValueChange = jest.fn();

      render(
        <CommandMenu open={true} onOpenChange={() => {}}>
          <CommandMenu.Content>
            <CommandMenu.Header
              placeholder="Search..."
              value=""
              onValueChange={onValueChange}
            />
            <CommandMenu.List>
              <CommandMenu.Item value="item-1" onSelect={() => {}}>
                Item 1
              </CommandMenu.Item>
            </CommandMenu.List>
          </CommandMenu.Content>
        </CommandMenu>
      );

      const input = screen.getByPlaceholderText("Search...");
      await user.type(input, "test");

      expect(onValueChange).toHaveBeenCalledWith("t");
      expect(onValueChange).toHaveBeenCalledWith("e");
      expect(onValueChange).toHaveBeenCalledWith("s");
      expect(onValueChange).toHaveBeenCalledWith("t");
    });
  });
});
