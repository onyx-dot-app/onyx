import { fireEvent, render, screen } from "@tests/setup/test-utils";
import SpreadsheetPreview from "@/app/craft/components/output-panel/SpreadsheetPreview";

it("switches sheets and identifies truncated previews", () => {
  render(
    <SpreadsheetPreview
      sheets={[
        { name: "Sales", rows: [["Region"], ["North"]], truncated: false },
        { name: "Totals", rows: [["Amount"], ["42"]], truncated: true },
      ]}
    />
  );
  expect(screen.getByText("North")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Totals" }));
  expect(screen.queryByText("North")).not.toBeInTheDocument();
  expect(screen.getByText("42")).toBeInTheDocument();
  expect(screen.getByText(/Preview limited to/)).toBeInTheDocument();
});
