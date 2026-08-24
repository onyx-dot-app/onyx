import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { Sheet } from "@/components/ui/sheet";
import { Text } from "@/components/ui/text";

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

function renderSheet(
  overrides: Partial<React.ComponentProps<typeof Sheet>> = {},
) {
  const props = {
    visible: true,
    onClose: jest.fn(),
    title: "Actions",
    children: <Text>Body</Text>,
    ...overrides,
  };
  const view = render(<Sheet {...props} />);
  return { ...props, toJSON: view.toJSON };
}

// Every `accessible` prop in the rendered tree, outermost first.
function accessibleFlags(node: unknown): boolean[] {
  if (node == null || typeof node !== "object") return [];
  const element = node as {
    props?: Record<string, unknown>;
    children?: unknown[];
  };
  const own =
    typeof element.props?.accessible === "boolean"
      ? [element.props.accessible]
      : [];
  const nested = (element.children ?? []).flatMap(accessibleFlags);
  return [...own, ...nested];
}

describe("Sheet", () => {
  it("renders its title and body", () => {
    renderSheet();
    expect(screen.getByText("Actions")).toBeTruthy();
    expect(screen.getByText("Body")).toBeTruthy();
  });

  it("omits the subtitle unless one is given", () => {
    renderSheet();
    expect(screen.queryByText("2.4 KB")).toBeNull();

    renderSheet({ subtitle: "2.4 KB" });
    expect(screen.getByText("2.4 KB")).toBeTruthy();
  });

  it("closes from the header button", () => {
    const props = renderSheet();
    fireEvent.press(screen.getByLabelText("Close"));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps its wrappers out of the accessibility tree", () => {
    // Pressable defaults `accessible` to true, and a view that is an accessibility element hides
    // its descendants from VoiceOver — the sheet would be read as one blob with Close unreachable.
    const flags = accessibleFlags(renderSheet().toJSON());

    // The two outermost are the scrim and the card.
    expect(flags.slice(0, 2)).toEqual([false, false]);
    // …and a real control inside them stays reachable.
    expect(screen.getByLabelText("Close")).toBeTruthy();
  });

  it("paints the gray card differently from the default one", () => {
    const standard = renderSheet().toJSON();
    const gray = renderSheet({ background: "gray" }).toJSON();

    expect(JSON.stringify(gray)).not.toEqual(JSON.stringify(standard));
  });
});
