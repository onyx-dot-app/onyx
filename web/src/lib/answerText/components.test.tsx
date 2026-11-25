import type { Components } from "react-markdown";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { AnswerMarkdown } from "@/lib/answerText/components";
import { ResponseCursorScope } from "@/lib/timeline/components/Response";

const OPEN_CODE = "Intro.\n\n```python\nx = 1";

test("the cursor marker hides while the last block is open code", () => {
  const { container, rerender } = render(
    <ResponseCursorScope working>
      <AnswerMarkdown content={OPEN_CODE} streaming cursor />
    </ResponseCursorScope>
  );
  const kinds = () =>
    Array.from(container.querySelectorAll("[data-response-cursor]")).map(
      (marker) => marker.getAttribute("data-response-cursor")
    );
  expect(kinds()).toEqual(["hidden"]);

  rerender(
    <ResponseCursorScope working>
      <AnswerMarkdown
        content={`${OPEN_CODE}\n\`\`\`\n\nMore`}
        streaming
        cursor
      />
    </ResponseCursorScope>
  );
  expect(kinds()).toEqual(["text"]);
});

test("the inline cursor hides while the last block is open code", () => {
  const { container } = render(
    <AnswerMarkdown content={OPEN_CODE} streaming cursor />
  );
  expect(container.querySelector(".animate-pulse")).toBeNull();
});

test("finished blocks do not re-render while the answer streams", () => {
  const rendered: string[] = [];
  const components: Components = {
    p: ({ children }) => {
      rendered.push(String(children));
      return <p>{children}</p>;
    },
  };
  const { rerender } = render(
    <AnswerMarkdown
      content={"First.\n\nSecond"}
      streaming
      components={components}
    />
  );
  rendered.length = 0;
  rerender(
    <AnswerMarkdown
      content={"First.\n\nSecond more"}
      streaming
      components={components}
    />
  );
  expect(rendered).toEqual(["Second more"]);
});

test("a fenced code block opts out of the answer's prose styles", async () => {
  render(
    <AnswerMarkdown
      content={'Here is the script:\n\n```python\nprint("hi")\n```\n'}
    />
  );

  const block = await screen.findByTestId("answer-code-block");
  // Prose styles tables; the code panel draws its lines as a table.
  expect(block).toHaveClass("not-prose");
  expect(block.closest(".prose")).not.toBeNull();
});

test("a streaming answer renders the same text as a finished one", () => {
  const content = [
    "# Results",
    "The first paragraph has **bold** text.",
    "The second paragraph follows.",
    "- one\n- two\n\n  more of two\n- three",
    "| a | b |\n| - | - |\n| 1 | 2 |",
    "```python\nx = 1\n\n\ny = 2\n```",
    "$$\na^2\n\n+ b^2\n$$",
    "The end.",
  ].join("\n\n");

  const { container: streamed } = render(
    <AnswerMarkdown content={content} streaming />
  );
  const { container: finished } = render(<AnswerMarkdown content={content} />);

  // One parse puts newline text between top-level blocks; split blocks do not.
  const text = (element: HTMLElement) =>
    (element.textContent ?? "").replace(/\s+/g, "");
  expect(text(streamed)).toBe(text(finished));
  expect(streamed.querySelectorAll(".prose")).toHaveLength(1);
});

test("a code block keeps its wrap choice when the answer finishes", async () => {
  const user = setupUser();
  const content = "Intro.\n\n```python\nprint(1)\n```\n\nThe end.";
  const { rerender } = render(<AnswerMarkdown content={content} streaming />);

  await user.click(screen.getByRole("button", { name: "Unwrap" }));
  rerender(<AnswerMarkdown content={content} />);

  expect(screen.getByRole("button", { name: "Wrap" })).toBeInTheDocument();
});
