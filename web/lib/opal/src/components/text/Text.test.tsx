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
