import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { z } from "zod";
import { defineComponent, createLibrary } from "@onyx/genui";
import type { Library, ActionEvent } from "@onyx/genui";
import { Renderer } from "./Renderer";

/**
 * Create a test library with simple React components.
 * Each component renders its props as data attributes for easy assertion.
 */
function makeTestLibrary(): Library {
  return createLibrary([
    defineComponent({
      name: "Text",
      description: "Text display",
      props: z.object({
        children: z.string(),
        headingH2: z.boolean().optional(),
      }),
      component: ({
        props,
      }: {
        props: { children: string; headingH2?: boolean };
      }) => {
        const Tag = props.headingH2 ? "h2" : "span";
        return <Tag data-testid="text">{props.children}</Tag>;
      },
    }),
    defineComponent({
      name: "Button",
      description: "Interactive button",
      props: z.object({
        children: z.string(),
        main: z.boolean().optional(),
        primary: z.boolean().optional(),
        actionId: z.string().optional(),
      }),
      component: ({
        props,
      }: {
        props: {
          children: string;
          main?: boolean;
          primary?: boolean;
          actionId?: string;
        };
      }) => (
        <button data-testid="button" data-action-id={props.actionId}>
          {props.children}
        </button>
      ),
    }),
    defineComponent({
      name: "Stack",
      description: "Vertical layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.enum(["none", "xs", "sm", "md", "lg", "xl"]).optional(),
      }),
      component: ({
        props,
      }: {
        props: { children?: unknown[]; gap?: string };
      }) => (
        <div data-testid="stack" data-gap={props.gap}>
          {props.children}
        </div>
      ),
    }),
    defineComponent({
      name: "Tag",
      description: "Label tag",
      props: z.object({
        title: z.string(),
        color: z.enum(["green", "purple", "blue", "gray", "amber"]).optional(),
      }),
      component: ({ props }: { props: { title: string; color?: string } }) => (
        <span data-testid="tag" data-color={props.color}>
          {props.title}
        </span>
      ),
    }),
  ]);
}

describe("Renderer", () => {
  it("returns null for null response", () => {
    const lib = makeTestLibrary();
    const { container } = render(<Renderer response={null} library={lib} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders a simple Text component", () => {
    const lib = makeTestLibrary();
    render(<Renderer response='root = Text("Hello World")' library={lib} />);
    expect(screen.getByTestId("text")).toHaveTextContent("Hello World");
  });

  it("renders a component with named args", () => {
    const lib = makeTestLibrary();
    render(
      <Renderer
        response='root = Tag("Status", color: "green")'
        library={lib}
      />,
    );
    const tag = screen.getByTestId("tag");
    expect(tag).toHaveTextContent("Status");
    expect(tag.dataset["color"]).toBe("green");
  });

  it("renders nested components via variable references", () => {
    const lib = makeTestLibrary();
    const input = `title = Text("Hello", headingH2: true)
btn = Button("Click me")
root = Stack([title, btn], gap: "md")`;

    render(<Renderer response={input} library={lib} />);

    expect(screen.getByTestId("stack")).toBeInTheDocument();
    expect(screen.getByTestId("text")).toHaveTextContent("Hello");
    expect(screen.getByTestId("button")).toHaveTextContent("Click me");
  });

  it("falls back to plain text for non-GenUI responses", () => {
    const lib = makeTestLibrary();
    const { container } = render(
      <Renderer
        response="Just a plain text response with no components."
        library={lib}
        fallbackToMarkdown={true}
      />,
    );
    expect(container.textContent).toContain("Just a plain text response");
  });

  it("returns null for non-GenUI when fallback disabled", () => {
    const lib = makeTestLibrary();
    const { container } = render(
      <Renderer
        response="plain text"
        library={lib}
        fallbackToMarkdown={false}
      />,
    );
    // Should render nothing meaningful (no parsed root, no fallback)
    // The div wrapper is still rendered
    const wrapper = container.firstChild as HTMLElement;
    // Inner content should be empty or minimal
    expect(wrapper.textContent).toBe("");
  });

  it("applies className to wrapper div", () => {
    const lib = makeTestLibrary();
    const { container } = render(
      <Renderer
        response='root = Text("test")'
        library={lib}
        className="my-custom-class"
      />,
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.classList.contains("my-custom-class")).toBe(true);
  });

  it("renders unknown components with placeholder", () => {
    const lib = makeTestLibrary();
    // Unknown component with no children renders as [ComponentName]
    const { container } = render(
      <Renderer response="root = UnknownWidget()" library={lib} />,
    );
    expect(container.textContent).toContain("[UnknownWidget]");
  });

  it("handles the full spec example", () => {
    const lib = makeTestLibrary();
    const input = `title = Text("Search Results", headingH2: true)
btn = Button("View All", main: true, primary: true, actionId: "viewAll")
root = Stack([title, btn], gap: "md")`;

    render(<Renderer response={input} library={lib} />);

    const heading = screen.getByTestId("text");
    expect(heading.tagName).toBe("H2");
    expect(heading).toHaveTextContent("Search Results");

    const button = screen.getByTestId("button");
    expect(button).toHaveTextContent("View All");
    expect(button.dataset["actionId"]).toBe("viewAll");

    const stack = screen.getByTestId("stack");
    expect(stack.dataset["gap"]).toBe("md");
  });
});

describe("Renderer — Error Boundary", () => {
  it("catches component render errors without crashing", () => {
    const lib = createLibrary([
      defineComponent({
        name: "Broken",
        description: "Always throws",
        props: z.object({ children: z.string() }),
        component: () => {
          throw new Error("Intentional test error");
        },
      }),
    ]);

    // Should not throw — error boundary catches it
    const { container } = render(
      <Renderer response='root = Broken("crash")' library={lib} />,
    );

    expect(container.textContent).toContain("failed to render");
  });
});

describe("Renderer — Streaming simulation", () => {
  it("re-renders as response grows", () => {
    const lib = makeTestLibrary();

    // Start with partial response
    const { rerender, container } = render(
      <Renderer
        response='title = Text("Hel'
        library={lib}
        isStreaming={true}
      />,
    );

    // Complete the response
    rerender(
      <Renderer
        response='title = Text("Hello World")\n'
        library={lib}
        isStreaming={false}
      />,
    );

    expect(screen.getByTestId("text")).toHaveTextContent("Hello World");
  });

  it("handles response reset (regeneration)", () => {
    const lib = makeTestLibrary();

    // First response
    const { rerender } = render(
      <Renderer
        response='root = Text("First")\n'
        library={lib}
        isStreaming={false}
      />,
    );

    expect(screen.getByTestId("text")).toHaveTextContent("First");

    // New response (shorter — indicates reset)
    rerender(
      <Renderer
        response='root = Text("New")\n'
        library={lib}
        isStreaming={false}
      />,
    );

    expect(screen.getByTestId("text")).toHaveTextContent("New");
  });
});
