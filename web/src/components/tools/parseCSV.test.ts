import { parseCSV } from "./CSVContent";

describe("parseCSV", () => {
  it("parses simple comma-separated rows", () => {
    expect(parseCSV("a,b,c\n1,2,3")).toEqual([
      ["a", "b", "c"],
      ["1", "2", "3"],
    ]);
  });

  it("preserves commas inside quoted fields", () => {
    expect(parseCSV('name,address\nAlice,"123 Main St, Apt 4"')).toEqual([
      ["name", "address"],
      ["Alice", "123 Main St, Apt 4"],
    ]);
  });

  it("handles escaped double quotes inside quoted fields", () => {
    expect(parseCSV('a,b\n"say ""hello""",world')).toEqual([
      ["a", "b"],
      ['say "hello"', "world"],
    ]);
  });

  it("handles newlines inside quoted fields", () => {
    expect(parseCSV('a,b\n"line1\nline2",val')).toEqual([
      ["a", "b"],
      ["line1\nline2", "val"],
    ]);
  });

  it("handles CRLF line endings", () => {
    expect(parseCSV("a,b\r\n1,2\r\n3,4")).toEqual([
      ["a", "b"],
      ["1", "2"],
      ["3", "4"],
    ]);
  });

  it("handles empty fields", () => {
    expect(parseCSV("a,b,c\n1,,3")).toEqual([
      ["a", "b", "c"],
      ["1", "", "3"],
    ]);
  });

  it("handles a single element", () => {
    expect(parseCSV("a")).toEqual([["a"]]);
  });

  it("handles a single row with no newline", () => {
    expect(parseCSV("a,b,c")).toEqual([["a", "b", "c"]]);
  });

  it("handles quoted fields that are entirely empty", () => {
    expect(parseCSV('a,b\n"",val')).toEqual([
      ["a", "b"],
      ["", "val"],
    ]);
  });

  it("handles multiple quoted fields with commas", () => {
    expect(parseCSV('"foo, bar","baz, qux"\n"1, 2","3, 4"')).toEqual([
      ["foo, bar", "baz, qux"],
      ["1, 2", "3, 4"],
    ]);
  });

  it("throws on unterminated quoted field", () => {
    expect(() => parseCSV('a,b\n"foo,bar')).toThrow(
      "Malformed CSV: unterminated quoted field"
    );
  });

  it("throws on unterminated quote at end of input", () => {
    expect(() => parseCSV('"unterminated')).toThrow(
      "Malformed CSV: unterminated quoted field"
    );
  });

  it("returns empty array for empty input", () => {
    expect(parseCSV("")).toEqual([]);
  });
});
