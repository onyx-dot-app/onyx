// Text children are branded (`string | RichStr | RichNodes`), never raw JSX.
// The `richNodes()` path exists for translated sentences that embed an inline
// component (next-intl `t.rich`), so what matters is that the nodes render
// verbatim — handlers intact — while typography still comes from `Text`.
import { render, screen, userEvent } from "@tests/setup/test-utils";
import { Text } from "@opal/components";
import { richNodes } from "@opal/utils";

describe("Text with RichNodes children", () => {
  it("renders the nodes verbatim, keeping interactive elements", async () => {
    const onClick = jest.fn();
    const user = userEvent.setup();
    render(
      <Text font="main-ui-body" color="text-04">
        {richNodes(
          <>
            Click <button onClick={onClick}>here</button> to continue.
          </>
        )}
      </Text>
    );

    await user.click(screen.getByRole("button", { name: "here" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("keeps the font and color presets on the wrapping tag", () => {
    render(
      <Text font="main-ui-body" color="text-04" data-testid="rich-text">
        {richNodes(<em>emphasis</em>)}
      </Text>
    );

    const wrapper = screen.getByTestId("rich-text");
    expect(wrapper).toHaveClass("font-main-ui-body", "text-text-04");
    expect(wrapper.querySelector("em")).toHaveTextContent("emphasis");
  });
});

// `wordWrap` and `textPosition` map their value straight to the utility class,
// so what is worth pinning is that the mapping happens at all and that nothing
// is emitted when the caller says nothing. A mistyped value would otherwise
// reach the DOM as a class that does not exist and fail silently.
describe("Text wordWrap", () => {
  const LONG_TOKEN = "asdf".repeat(125);

  it("emits no wrapping class when unset", () => {
    render(
      <Text font="main-ui-body" color="text-04" data-testid="unset">
        {LONG_TOKEN}
      </Text>
    );

    const el = screen.getByTestId("unset");
    for (const cls of [
      "whitespace-nowrap",
      "wrap-normal",
      "wrap-break-word",
      "wrap-anywhere",
      "break-all",
      "break-keep",
    ]) {
      expect(el).not.toHaveClass(cls);
    }
  });

  it.each([
    "whitespace-nowrap",
    "wrap-normal",
    "wrap-break-word",
    "wrap-anywhere",
    "break-all",
    "break-keep",
  ] as const)("applies %s", (mode) => {
    render(
      <Text
        font="main-ui-body"
        color="text-04"
        wordWrap={mode}
        data-testid="wrapped"
      >
        {LONG_TOKEN}
      </Text>
    );

    expect(screen.getByTestId("wrapped")).toHaveClass(mode);
  });

  // `overflow-wrap` inherits, so omitting the prop cannot undo a value an
  // ancestor set. Stating `wrap-normal` is the only way to say "do not break".
  it("can state normal wrapping explicitly, to override an inherited value", () => {
    render(
      <div className="wrap-anywhere">
        <Text
          font="main-ui-body"
          color="text-04"
          wordWrap="wrap-normal"
          data-testid="reset"
        >
          {LONG_TOKEN}
        </Text>
      </div>
    );

    expect(screen.getByTestId("reset")).toHaveClass("wrap-normal");
  });
});

describe("Text textPosition", () => {
  it.each(["text-start", "text-center", "text-end", "text-justify"] as const)(
    "applies %s on a block tag",
    (position) => {
      render(
        <Text
          as="p"
          font="main-ui-body"
          color="text-04"
          textPosition={position}
          data-testid="aligned"
        >
          Aligned text
        </Text>
      );

      expect(screen.getByTestId("aligned")).toHaveClass(position);
    }
  );

  it("emits no alignment class when unset", () => {
    render(
      <Text as="p" font="main-ui-body" color="text-04" data-testid="plain">
        Plain text
      </Text>
    );

    const el = screen.getByTestId("plain");
    for (const cls of [
      "text-start",
      "text-center",
      "text-end",
      "text-justify",
    ]) {
      expect(el).not.toHaveClass(cls);
    }
  });
});
