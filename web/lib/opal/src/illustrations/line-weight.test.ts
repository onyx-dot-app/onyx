import { illustrationStrokeWidth } from "@opal/illustrations/line-weight";

const VIEWBOX_SIZE = 120;

describe("illustrationStrokeWidth", () => {
  it.each([
    [2.5, 64],
    [3.5, 120],
    [2.5, 32],
    [3, 92],
    [3.5, 240],
  ])("renders %s px lines at size %s", (px, size) => {
    expect((illustrationStrokeWidth(size) * size) / VIEWBOX_SIZE).toBeCloseTo(
      px
    );
  });

  it("assumes the 120 px size without a size", () => {
    expect(illustrationStrokeWidth()).toBe(3.5);
  });
});
