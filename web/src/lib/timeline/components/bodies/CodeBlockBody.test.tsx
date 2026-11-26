import { act, render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { MAX_HIGHLIGHTED_CHARACTERS } from "@/lib/codeHighlight/hooks";
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

test("code that grows while streaming ends highlighted like finished code", async () => {
  const steps = [
    "/* a comment",
    "/* a comment\nthat spans",
    "/* a comment\nthat spans\nlines */\nconst s = `a",
    "/* a comment\nthat spans\nlines */\nconst s = `a\nb`;\nconst n = 1;",
  ];
  const finalCode = steps[steps.length - 1] ?? "";
  const linesHtml = (container: HTMLElement) =>
    Array.from(container.querySelectorAll(".opal-code-panel-code")).map(
      (cell) => cell.innerHTML
    );

  const streamed = render(<CodeBlockBody code="" language="ts" streaming />);
  for (const step of steps) {
    streamed.rerender(<CodeBlockBody code={step} language="ts" streaming />);
    if (step.includes("\n")) {
      await waitFor(() =>
        expect(shikiTokens(streamed.container).length).toBeGreaterThan(0)
      );
    }
  }
  streamed.rerender(<CodeBlockBody code={finalCode} language="ts" />);
  await waitFor(() =>
    expect(
      Array.from(streamed.container.querySelectorAll(".opal-code-panel-code"))
        .at(-1)
        ?.querySelector("span[style]")
    ).not.toBeNull()
  );

  const finished = render(<CodeBlockBody code={finalCode} language="ts" />);
  await waitFor(() =>
    expect(linesHtml(finished.container)).toEqual(linesHtml(streamed.container))
  );
  expect(linesHtml(finished.container)).toHaveLength(6);
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

test.each([
  ["dos", "echo off"],
  ["gitignore", "# build output"],
  ["tsx", "const a = <div />;"],
])("a %s block gets Shiki tokens", async (language, code) => {
  const { container } = render(
    <CodeBlockBody code={code} language={language} />
  );
  await waitFor(() => expect(shikiTokens(container).length).toBeGreaterThan(0));
});

test("finished code above the highlight cap stays plain", async () => {
  // Highlight a small block first, so the grammar is loaded and cached.
  const small = render(<CodeBlockBody code="const a = 1;" language="ts" />);
  await waitFor(() =>
    expect(shikiTokens(small.container).length).toBeGreaterThan(0)
  );

  const code = `const a = 1;\n${"// filler\n".repeat(MAX_HIGHLIGHTED_CHARACTERS / 9)}`;
  expect(code.length).toBeGreaterThan(MAX_HIGHLIGHTED_CHARACTERS);
  const { container } = render(<CodeBlockBody code={code} language="ts" />);
  await act(async () => {});
  expect(shikiTokens(container)).toHaveLength(0);
});
