import { parseCsv } from "@/app/craft/components/output-panel/CsvPreview";

it("parses quoted separators, quotes, multiline cells, and empty cells", () => {
  expect(
    parseCsv(
      'name,description,empty\r\n"A,B","a ""quote""\nand another line",\r\n'
    )
  ).toEqual({
    rows: [
      ["name", "description", "empty"],
      ["A,B", 'a "quote"\nand another line', ""],
    ],
    truncated: false,
  });
});
it("bounds large previews without reading arbitrary numbers of rows", () => {
  const result = parseCsv(Array.from({ length: 1200 }, () => "a,b").join("\n"));
  expect(result.rows).toHaveLength(1000);
  expect(result.truncated).toBe(true);
});

it("preserves an empty quoted cell and strips a UTF-8 marker", () => {
  expect(parseCsv('""').rows).toEqual([[""]]);
  expect(parseCsv("\uFEFFname,value\na,b").rows).toEqual([
    ["name", "value"],
    ["a", "b"],
  ]);
});
