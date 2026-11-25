import { render, screen } from "@tests/setup/test-utils";
import { AnswerMarkdown } from "@/lib/answerText/components";

test("a GitHub alert renders as a titled callout without its marker", () => {
  const { container } = render(
    <AnswerMarkdown
      content={"> [!WARNING]\n> Back up the database first.\n\nAfter."}
    />
  );

  const callout = screen.getByRole("note");
  expect(callout).toHaveAttribute("data-alert", "warning");
  expect(callout).toHaveTextContent("Warning");
  expect(callout).toHaveTextContent("Back up the database first.");
  expect(callout).not.toHaveTextContent("[!WARNING]");
  expect(container.querySelector("blockquote")).toBeNull();
});

test("a blockquote without a marker stays a blockquote", () => {
  const { container } = render(
    <AnswerMarkdown content={"> [!NOTE] inline is text\n\n> Plain quote."} />
  );

  expect(screen.queryByRole("note")).toBeNull();
  const quotes = container.querySelectorAll("blockquote");
  expect(quotes).toHaveLength(2);
  expect(quotes[0]).toHaveTextContent("[!NOTE] inline is text");
});

test("a details block renders its summary and markdown body", () => {
  const { container } = render(
    <AnswerMarkdown
      content={
        "<details>\n<summary>Show <b>steps</b></summary>\n\n- **one**\n- two\n\n</details>\n\nAfter."
      }
    />
  );

  const details = container.querySelector("details");
  expect(details).not.toBeNull();
  expect(details).not.toHaveAttribute("open");
  expect(details?.querySelector("summary")).toHaveTextContent(/^Show steps$/);
  expect(details?.querySelector("strong")).toHaveTextContent("one");
  expect(details?.querySelectorAll("li")).toHaveLength(2);
  expect(container).toHaveTextContent("After.");
});

test("an open details block starts open", () => {
  const { container } = render(
    <AnswerMarkdown
      content={"<details open>\n<summary>More</summary>\n\nBody\n\n</details>"}
    />
  );

  expect(container.querySelector("details")).toHaveAttribute("open");
});

test("details tags that share a line block with text or each other still nest", () => {
  const { container } = render(
    <AnswerMarkdown
      content={
        "<details>\n<summary>Outer &amp; more</summary>\nFirst line\n\n<details>\n<summary>Inner</summary>\n\nInner body\n\n</details>\n</details>\n\nAfter."
      }
    />
  );

  const outer = container.querySelector("details");
  expect(outer?.querySelector("summary")).toHaveTextContent(/^Outer & more$/);
  expect(outer).toHaveTextContent("First line");
  const inner = outer?.querySelector("details");
  expect(inner?.querySelector("summary")).toHaveTextContent(/^Inner$/);
  expect(inner).toHaveTextContent("Inner body");
  expect(container.querySelector("details + p")).toHaveTextContent("After.");
});

test("a task list shows read-only checkboxes without bullets", () => {
  render(<AnswerMarkdown content={"- [x] Done\n- [ ] To do"} />);

  const boxes = screen.getAllByRole("checkbox");
  expect(boxes).toHaveLength(2);
  expect(boxes[0]).toBeChecked();
  expect(boxes[1]).not.toBeChecked();
  for (const box of boxes) {
    expect(box).toHaveAttribute("aria-disabled", "true");
  }
  expect(screen.getByText("Done").closest("li")).toHaveClass("list-none");
});

test("a loose task list keeps the checkbox out of the paragraph", () => {
  const { container } = render(
    <AnswerMarkdown content={"- [x] Done\n\n- [ ] To do"} />
  );

  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  expect(container.querySelector("p [role='checkbox']")).toBeNull();
  expect(container.querySelector("p")).toHaveTextContent("Done");
});
