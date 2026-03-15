import React from "react";
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FallbackRenderer } from "./FallbackRenderer";

describe("FallbackRenderer", () => {
  it("renders plain text content", () => {
    const { container } = render(
      <FallbackRenderer content="Hello, this is plain text." />,
    );
    expect(container.textContent).toContain("Hello, this is plain text.");
  });

  it("splits paragraphs on double newlines", () => {
    const { container } = render(
      <FallbackRenderer content={"First paragraph.\n\nSecond paragraph."} />,
    );
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs.length).toBe(2);
    expect(paragraphs[0]!.textContent).toBe("First paragraph.");
    expect(paragraphs[1]!.textContent).toBe("Second paragraph.");
  });

  it("renders code blocks in pre/code tags", () => {
    const { container } = render(
      <FallbackRenderer content={"```js\nconsole.log('hi');\n```"} />,
    );
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    const code = container.querySelector("code");
    expect(code!.textContent).toBe("console.log('hi');");
  });

  it("handles empty content", () => {
    const { container } = render(<FallbackRenderer content="" />);
    // Should render without crashing
    expect(container).toBeDefined();
  });

  it("handles content with only newlines", () => {
    const { container } = render(<FallbackRenderer content="\n\n\n" />);
    expect(container).toBeDefined();
  });
});
