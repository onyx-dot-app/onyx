/** The connector page's run link: `run=<id>` and an optional `run_kind`, an index run when absent. */
import {
  parseRunParams,
  writeRunParams,
} from "@/views/admin/connectors/ConnectorDetailPage/runLink";

function parse(query: string) {
  return parseRunParams(new URLSearchParams(query));
}

describe("parseRunParams", () => {
  it("reads the id and kind", () => {
    expect(parse("tab=indexing&run=30&run_kind=pruning")).toEqual({
      id: 30,
      kind: "pruning",
    });
  });

  it("reads an index run when run_kind is absent", () => {
    expect(parse("run=30")).toEqual({ id: 30, kind: "indexing" });
  });

  it.each([
    "",
    "run=0",
    "run=-3",
    "run=1.5",
    "run=abc",
    "run=30&run_kind=bogus",
  ])("rejects %p whole", (query) => {
    expect(parse(query)).toBeNull();
  });
});

describe("writeRunParams", () => {
  it("writes the shape the reader takes back", () => {
    const query = new URLSearchParams("tab=indexing");
    writeRunParams(query, { id: 44, kind: "checks" });
    expect(query.toString()).toBe("tab=indexing&run=44&run_kind=checks");
    expect(parseRunParams(query)).toEqual({ id: 44, kind: "checks" });
  });

  it("drops the run so a reload does not reopen it", () => {
    const query = new URLSearchParams("tab=indexing&run=44&run_kind=checks");
    writeRunParams(query, null);
    expect(query.toString()).toBe("tab=indexing");
  });
});
