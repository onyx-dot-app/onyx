import {
  parseCsv,
  parseSpreadsheetPreview,
  parseSpreadsheetCsv,
} from "@/lib/csv";

describe("parseCsv", () => {
  it("parses simple comma-separated rows", () => {
    expect(parseCsv("a,b,c\n1,2,3").rows).toEqual([
      ["a", "b", "c"],
      ["1", "2", "3"],
    ]);
  });

  it("preserves commas inside quoted fields", () => {
    expect(parseCsv('name,address\nAlice,"123 Main St, Apt 4"').rows).toEqual([
      ["name", "address"],
      ["Alice", "123 Main St, Apt 4"],
    ]);
  });

  it("handles escaped double quotes inside quoted fields", () => {
    expect(parseCsv('a,b\n"say ""hello""",world').rows).toEqual([
      ["a", "b"],
      ['say "hello"', "world"],
    ]);
  });

  it("handles newlines inside quoted fields", () => {
    expect(parseCsv('a,b\n"line1\nline2",val').rows).toEqual([
      ["a", "b"],
      ["line1\nline2", "val"],
    ]);
  });

  it("handles CRLF line endings", () => {
    expect(parseCsv("a,b\r\n1,2\r\n3,4").rows).toEqual([
      ["a", "b"],
      ["1", "2"],
      ["3", "4"],
    ]);
  });

  it("handles empty fields", () => {
    expect(parseCsv("a,b,c\n1,,3").rows).toEqual([
      ["a", "b", "c"],
      ["1", "", "3"],
    ]);
  });

  it("handles a single element", () => {
    expect(parseCsv("a").rows).toEqual([["a"]]);
  });

  it("handles a single row with no newline", () => {
    expect(parseCsv("a,b,c").rows).toEqual([["a", "b", "c"]]);
  });

  it("handles quoted fields that are entirely empty", () => {
    expect(parseCsv('a,b\n"",val').rows).toEqual([
      ["a", "b"],
      ["", "val"],
    ]);
  });

  it("handles multiple quoted fields with commas", () => {
    expect(parseCsv('"foo, bar","baz, qux"\n"1, 2","3, 4"').rows).toEqual([
      ["foo, bar", "baz, qux"],
      ["1, 2", "3, 4"],
    ]);
  });

  it("throws on unterminated quoted field", () => {
    expect(() => parseCsv('a,b\n"foo,bar').rows).toThrow(
      "Malformed CSV: unterminated quoted field"
    );
  });

  it("throws on unterminated quote at end of input", () => {
    expect(() => parseCsv('"unterminated').rows).toThrow(
      "Malformed CSV: unterminated quoted field"
    );
  });

  it("returns empty array for empty input", () => {
    expect(parseCsv("").rows).toEqual([]);
  });
});

it.each(['"account"oops,balance', '""oops,balance', '"account" ,balance'])(
  "rejects trailing text after a closed quoted field: %s",
  (content) => {
    expect(() => parseCsv(content)).toThrow(
      "Malformed CSV: text after a quoted field"
    );
  }
);
it("rejects quotes within an unquoted field", () => {
  expect(() => parseCsv('account"oops,balance').rows).toThrow(
    "Malformed CSV: quote in an unquoted field"
  );
});
it("accepts separators and record endings after a closed quoted field", () => {
  expect(parseCsv('"account","balance"\r\n"checking","42"').rows).toEqual([
    ["account", "balance"],
    ["checking", "42"],
  ]);
});

it("preserves an empty quoted cell and strips a UTF-8 marker", () => {
  expect(parseCsv('""').rows).toEqual([[""]]);
  expect(parseCsv("\uFEFFname,value\na,b").rows).toEqual([
    ["name", "value"],
    ["a", "b"],
  ]);
});

it("marks character-limited quoted input as truncated", () => {
  expect(parseCsv('a,b\n"long value",c', { maxCharacters: 8 })).toEqual({
    rows: [["a", "b"], ["lon"]],
    truncated: true,
  });
});

// Spreadsheet payload validation.
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

it("separates malformed CSV from a valid empty spreadsheet", () => {
  expect(parseSpreadsheetCsv('"account"oops,balance')).toEqual({
    rows: [],
    error: true,
  });
  expect(parseSpreadsheetCsv("")).toEqual({ rows: [], error: false });
});
