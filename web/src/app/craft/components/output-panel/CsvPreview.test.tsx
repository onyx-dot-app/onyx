import { render, screen } from "@tests/setup/test-utils";
import {
  CsvPreview,
  parseCsv,
} from "@/app/craft/components/output-panel/CsvPreview";

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

it("rejects unterminated quoted fields", () => {
  expect(() => parseCsv('a,b\n"unfinished')).toThrow(
    "unterminated quoted field"
  );
});
it("bounds the combined number of rendered cells", () => {
  const content = Array.from({ length: 1000 }, () =>
    Array.from({ length: 100 }, () => "value").join(",")
  ).join("\n");
  const result = parseCsv(content);
  expect(result.rows.flat()).toHaveLength(5000);
  expect(result.truncated).toBe(true);
});

it("reports malformed CSV instead of rendering a plausible partial table", () => {
  render(<CsvPreview content={'a,b\n"unfinished'} />);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "incomplete quoted field"
  );
  expect(screen.queryByRole("cell")).not.toBeInTheDocument();
});
