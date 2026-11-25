import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { CodeBlockBody } from "@/lib/timeline/components/bodies/CodeBlockBody";

const LONG_LINE = `curl -X POST https://api.example.com/v1/chat -d '${"x".repeat(200)}'`;

function lines(container: HTMLElement): Element | null {
  return container.querySelector(".opal-code-panel-lines");
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
