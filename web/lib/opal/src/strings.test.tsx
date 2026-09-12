import { render, screen } from "@tests/setup/test-utils";
import {
  OpalStringsProvider,
  defaultOpalStrings,
  useOpalStrings,
} from "@opal/strings";

function Probe() {
  const strings = useOpalStrings();
  return (
    <>
      <span>{strings.copy}</span>
      <span>{strings.selectedItemCount(2)}</span>
      <span>{strings.showing("1~10", "22")}</span>
    </>
  );
}

describe("useOpalStrings", () => {
  it("falls back to the English defaults", () => {
    render(<Probe />);
    expect(screen.getByText("Copy")).toBeInTheDocument();
    expect(screen.getByText("2 items selected")).toBeInTheDocument();
    expect(screen.getByText("Showing 1~10 of 22")).toBeInTheDocument();
  });

  it("reads the provided strings", () => {
    render(
      <OpalStringsProvider
        strings={{
          ...defaultOpalStrings,
          copy: "نسخ",
          selectedItemCount: (count) => `${count} محدد`,
          showing: (range, total) => ["عرض ", range, " من ", total],
        }}
      >
        <Probe />
      </OpalStringsProvider>
    );
    expect(screen.getByText("نسخ")).toBeInTheDocument();
    expect(screen.getByText("2 محدد")).toBeInTheDocument();
    expect(screen.getByText("عرض 1~10 من 22")).toBeInTheDocument();
  });
});
