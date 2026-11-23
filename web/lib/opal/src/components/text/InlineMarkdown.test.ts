import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { codeSpan, markdown } from "@opal/utils";
import InlineMarkdown, {
  toPlainString,
} from "@opal/components/text/InlineMarkdown";

describe("InlineMarkdown", () => {
  it("renders a code span as an LTR isolate inside RTL text", () => {
    const html = renderToStaticMarkup(
      createElement(InlineMarkdown, { content: "افتح `src/a.py` الآن" })
    );
    expect(html).toMatch(/افتح <code dir="ltr"[^>]*>src\/a\.py<\/code> الآن/);
  });

  it("keeps a code span with line breaks in one code element", () => {
    const html = renderToStaticMarkup(
      createElement(InlineMarkdown, {
        content: `Read ${codeSpan("a\n\n[click](https://evil.example)\n- b")}`,
      })
    );
    expect(html).not.toContain("<a");
    expect(html).not.toContain("<li");
    expect(html.match(/<code/g)).toHaveLength(1);
  });
});

describe("toPlainString", () => {
  it("returns plain strings unchanged", () => {
    expect(toPlainString("Hello world")).toBe("Hello world");
  });

  it("returns empty plain strings unchanged", () => {
    expect(toPlainString("")).toBe("");
  });

  it("returns RichStr without markdown unchanged", () => {
    expect(toPlainString(markdown("Hello world"))).toBe("Hello world");
  });

  it("strips link syntax, keeping the label", () => {
    expect(
      toPlainString(
        markdown("[Onyx 0.0.0-dev](https://docs.onyx.app/changelog)")
      )
    ).toBe("Onyx 0.0.0-dev");
  });

  it("strips bold (**) syntax", () => {
    expect(toPlainString(markdown("**bold text**"))).toBe("bold text");
  });

  it("strips bold (__) syntax", () => {
    expect(toPlainString(markdown("__bold text__"))).toBe("bold text");
  });

  it("strips italic (*) syntax", () => {
    expect(toPlainString(markdown("*italic*"))).toBe("italic");
  });

  it("strips italic (_) syntax", () => {
    expect(toPlainString(markdown("_italic_"))).toBe("italic");
  });

  it("preserves underscores inside identifiers", () => {
    expect(toPlainString(markdown("snake_case_word"))).toBe("snake_case_word");
  });

  it("preserves double underscores inside identifiers", () => {
    expect(toPlainString(markdown("foo__bar__baz"))).toBe("foo__bar__baz");
  });

  it("strips strikethrough syntax", () => {
    expect(toPlainString(markdown("~~struck~~"))).toBe("struck");
  });

  it("strips inline code syntax", () => {
    expect(toPlainString(markdown("`code`"))).toBe("code");
  });

  it("collapses newlines into single spaces", () => {
    expect(toPlainString(markdown("line one", "line two"))).toBe(
      "line one line two"
    );
  });

  it("strips combined inline syntax", () => {
    expect(
      toPlainString(markdown("**bold** and *italic* and `code` and ~~struck~~"))
    ).toBe("bold and italic and code and struck");
  });

  it("strips link with bold label", () => {
    expect(toPlainString(markdown("[**bold link**](https://onyx.app)"))).toBe(
      "bold link"
    );
  });

  it("trims leading and trailing whitespace", () => {
    expect(toPlainString(markdown("  hello  "))).toBe("hello");
  });
});
