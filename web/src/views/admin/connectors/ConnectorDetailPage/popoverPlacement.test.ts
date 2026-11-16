/** Where the floating panels open by content width. */
import * as placement from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";

type Panel = "failedDocs" | "stackTrace";
type PlacementFor = (panel: Panel, contentWidth: number) => "beside" | "below";

/** `popoverPlacementFor(panel, contentWidth)`, the switch both panels share. */
function placementFor(): PlacementFor {
  const fn = (placement as Record<string, unknown>).popoverPlacementFor;
  expect(typeof fn).toBe("function");
  return fn as PlacementFor;
}

describe("AC-1/AC-2: popover placement by content width", () => {
  it("AC-1: at 1024 content width and above the stack trace opens beside the side panel, on its left, start-aligned", () => {
    const placementOf = placementFor();
    expect(placementOf("stackTrace", 1024)).toBe("beside");
    expect(placementOf("stackTrace", 1440)).toBe("beside");
    expect(placement.PLACEMENT_PROPS.beside).toEqual({
      side: "left",
      align: "start",
    });
  });

  it("AC-1: the failed documents panel opens under the message card, end-aligned, at every width", () => {
    const placementOf = placementFor();
    expect(placementOf("failedDocs", 1440)).toBe("below");
    expect(placementOf("failedDocs", 1024)).toBe("below");
    expect(placementOf("failedDocs", 672)).toBe("below");
    expect(placement.PLACEMENT_PROPS.below).toEqual({
      side: "bottom",
      align: "end",
    });
  });

  it("AC-2: below 1024 content width both panels open under the message card", () => {
    const placementOf = placementFor();
    expect(placementOf("stackTrace", 1023)).toBe("below");
    expect(placementOf("stackTrace", 672)).toBe("below");
    expect(placementOf("failedDocs", 1023)).toBe("below");
  });
});
