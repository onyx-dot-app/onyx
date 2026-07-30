import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { makeSearchDoc } from "@/chat/__tests__/fixtures";
import { SourceRow } from "@/components/chat/SourceRow";

describe("SourceRow", () => {
  it("renders the title, meta and snippet and fires onPress", () => {
    const onPress = jest.fn();
    const doc = makeSearchDoc({
      semantic_identifier: "Acme Report",
      link: "https://www.acme.com/r",
      blurb: "Quarterly results.",
      match_highlights: [],
    });
    render(<SourceRow doc={doc} onPress={onPress} />);

    expect(screen.getByText("Acme Report")).toBeTruthy();
    expect(screen.getByText(/acme\.com/)).toBeTruthy();
    expect(screen.getByText("Quarterly results.")).toBeTruthy();

    fireEvent.press(screen.getByRole("button"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("strips <hi> highlight markup from the snippet", () => {
    const doc = makeSearchDoc({
      match_highlights: ["the <hi>quarter</hi> results"],
    });
    render(<SourceRow doc={doc} onPress={jest.fn()} />);
    expect(screen.getByText("the quarter results")).toBeTruthy();
  });
});
