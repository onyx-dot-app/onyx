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
