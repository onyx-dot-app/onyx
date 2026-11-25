import { render, screen } from "@tests/setup/test-utils";
import { AnswerMarkdown } from "@/lib/answerText/components";

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
