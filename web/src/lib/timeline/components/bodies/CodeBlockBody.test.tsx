import { render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { CodeBlockBody } from "@/lib/timeline/components/bodies/CodeBlockBody";

const LONG_LINE = `curl -X POST https://api.example.com/v1/chat -d '${"x".repeat(200)}'`;

function lines(container: HTMLElement): Element | null {
  return container.querySelector(".opal-code-panel-lines");
}

function shikiTokens(container: HTMLElement): Element[] {
  return Array.from(
    container.querySelectorAll('.opal-code-panel-code span[style*="--shiki"]')
  );
}

test("a tagged block wraps long lines until the user turns wrapping off", async () => {
  const { container } = render(
    <CodeBlockBody code={LONG_LINE} language="bash" />
  );
  expect(lines(container)).not.toHaveAttribute("data-nowrap");

  await userEvent.click(screen.getByRole("button", { name: "Unwrap" }));
  expect(lines(container)).toHaveAttribute("data-nowrap");

  await userEvent.click(screen.getByRole("button", { name: "Wrap" }));
  expect(lines(container)).not.toHaveAttribute("data-nowrap");
});

test("a block shows plain text first, then Shiki tokens", async () => {
  const { container } = render(
    <CodeBlockBody code={"const answer = 42;"} language="ts" />
  );
  expect(shikiTokens(container)).toHaveLength(0);
  expect(container).toHaveTextContent("const answer = 42;");

  await waitFor(() => expect(shikiTokens(container).length).toBeGreaterThan(0));
  expect(container).toHaveTextContent("const answer = 42;");
});

test("a streaming block keeps its growing last line plain", async () => {
  const { container } = render(
    <CodeBlockBody
      code={"/* a comment\nthat ends */\nconst x"}
      language="ts"
      streaming
    />
  );

  await waitFor(() => expect(shikiTokens(container).length).toBeGreaterThan(0));
  const codeCells = container.querySelectorAll(".opal-code-panel-code");
  expect(codeCells[1]?.querySelector("span[style]")).not.toBeNull();
  expect(codeCells[2]?.querySelector("span[style]")).toBeNull();
  expect(codeCells[2]).toHaveTextContent("const x");
});

test("the header shows the file name in place of the language", () => {
  render(<CodeBlockBody code="x" language="ts" fileName="src/a.ts" />);
  expect(screen.getByText("src/a.ts")).toBeInTheDocument();
  expect(screen.queryByText("ts")).toBeNull();
});

test("an untagged block gets a header with copy and wrap controls", () => {
  const { container } = render(<CodeBlockBody code="plain words" />);
  const header = container.querySelector(".opal-code-panel-header");
  expect(header).toHaveTextContent("text");
  // The wrap toggle and the copy button.
  expect(header?.querySelectorAll("button")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Unwrap" })).toBeInTheDocument();
});
