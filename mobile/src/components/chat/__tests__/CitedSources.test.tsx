import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import {
  makeCitationPacket,
  makeSearchDoc,
  makeSearchDocsPacket,
} from "@/chat/__tests__/fixtures";
import { selectSources } from "@/chat/citations";
import { createInitialState, processPackets } from "@/chat/messageProcessor";
import {
  CitedSourcesBar,
  CitedSourcesSheet,
} from "@/components/chat/CitedSources";

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

describe("CitedSourcesSheet", () => {
  it("renders the cited and more sections from processed state", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeSearchDocsPacket([
        makeSearchDoc({ document_id: "d1", semantic_identifier: "Cited Doc" }),
        makeSearchDoc({ document_id: "d2", semantic_identifier: "Other Doc" }),
      ]),
      makeCitationPacket(1, "d1"),
    ]);

    render(
      <CitedSourcesSheet
        visible
        sources={selectSources(state)}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByText("Cited Sources")).toBeTruthy();
    expect(screen.getByText("Cited Doc")).toBeTruthy();
    expect(screen.getByText("More")).toBeTruthy();
    expect(screen.getByText("Other Doc")).toBeTruthy();
    expect(screen.queryByText("User Files")).toBeNull();
  });
});

describe("CitedSourcesBar", () => {
  it("shows the source count and fires onPress", () => {
    const onPress = jest.fn();
    render(<CitedSourcesBar iconDocs={[]} count={3} onPress={onPress} />);
    expect(screen.getByText("Sources · 3")).toBeTruthy();

    fireEvent.press(screen.getByRole("button"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});
