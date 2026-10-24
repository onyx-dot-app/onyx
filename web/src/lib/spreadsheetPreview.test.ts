import { utils, write, type BookType } from "xlsx";
import { parseSpreadsheet } from "@/lib/spreadsheetPreview";

function workbookBytes(
  bookType: BookType,
  rows: (string | number)[][]
): ArrayBuffer {
  const book = utils.book_new();
  utils.book_append_sheet(book, utils.aoa_to_sheet(rows), "Data");
  utils.book_append_sheet(book, utils.aoa_to_sheet([["Other sheet"]]), "Notes");
  return write(book, { type: "array", bookType });
}

it.each<BookType>(["xlsx", "xls", "ods"])(
  "reads %s values and multiple worksheets",
  (type) => {
    const sheets = parseSpreadsheet(
      workbookBytes(type, [
        ["Name", "Total"],
        ["Alice", 12],
      ])
    );
    expect(sheets).toEqual([
      {
        name: "Data",
        rows: [
          ["Name", "Total"],
          ["Alice", "12"],
        ],
        truncated: false,
      },
      { name: "Notes", rows: [["Other sheet"]], truncated: false },
    ]);
  }
);

it("bounds large worksheet ranges and reports truncation", () => {
  const rows = Array.from({ length: 1100 }, () =>
    Array.from({ length: 110 }, () => "value")
  );
  const [sheet] = parseSpreadsheet(workbookBytes("xlsx", rows));
  expect(sheet?.rows.flat()).toHaveLength(5000);
  expect(sheet?.rows[0]).toHaveLength(100);
  expect(sheet?.truncated).toBe(true);
});

it("keeps spreadsheet markup as literal cell text", () => {
  const [sheet] = parseSpreadsheet(
    workbookBytes("xlsx", [["<script>alert(1)</script>"]])
  );
  expect(sheet?.rows[0]).toEqual(["<script>alert(1)</script>"]);
});
