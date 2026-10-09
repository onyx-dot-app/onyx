import { parseSpreadsheetPreview } from "@/components/tools/SpreadsheetContent";

it("validates spreadsheet sheets before rendering their shared CSV content", () => {
  const sheets = [{ name: "Sheet 1", csv: "a,b\n1,2", truncated: false }];
  expect(parseSpreadsheetPreview(JSON.stringify({ sheets }))).toEqual({
    sheets,
  });
  expect(
    parseSpreadsheetPreview(JSON.stringify({ sheets: [null] }))
  ).toBeNull();
  expect(
    parseSpreadsheetPreview(
      JSON.stringify({
        sheets: [{ name: "Sheet 1", csv: 42, truncated: false }],
      })
    )
  ).toBeNull();
  expect(
    parseSpreadsheetPreview(
      JSON.stringify({ sheets: [{ name: "Sheet 1", csv: "a,b" }] })
    )
  ).toBeNull();
});
