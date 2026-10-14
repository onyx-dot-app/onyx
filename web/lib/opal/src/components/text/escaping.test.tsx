import { render, screen } from "@testing-library/react";
import InlineMarkdown, {
  toPlainString,
} from "@opal/components/text/InlineMarkdown";
import { escapeMarkdown, markdown } from "@opal/utils";

it("renders an untrusted name as text inside a formatted title", () => {
  const name =
    "[Click](https://example.com) **admin** `code` <https://example.com>";
  const { container } = render(
    <InlineMarkdown content={`Share **${escapeMarkdown(name)}**`} />
  );
  expect(screen.queryByRole("link", { name: "Click" })).not.toBeInTheDocument();
  for (const link of screen.getAllByRole("link")) {
    expect(link).toHaveAttribute("href", link.textContent);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  expect(container.textContent).toBe(`Share ${name}`);
  expect(container.querySelectorAll("strong")).toHaveLength(1);
  expect(container.querySelector("code")).toBeNull();
});

it("keeps escaped names readable in plain title attributes", () => {
  const name = "[Click](/account) <admin> **name** & &#42;";
  expect(toPlainString(markdown(`Share *${escapeMarkdown(name)}*`))).toBe(
    `Share ${name}`
  );
});

it("does not decode surrogate references in plain titles", () => {
  expect(toPlainString(markdown("&#55296;"))).toBe("&#55296;");
});
