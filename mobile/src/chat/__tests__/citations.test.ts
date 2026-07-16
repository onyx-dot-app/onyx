import { describe, expect, it } from "@jest/globals";

import { domainOf, faviconUrl, selectSources } from "@/chat/citations";
import { createInitialState, processPackets } from "@/chat/messageProcessor";

import {
  makeCitationPacket,
  makeSearchDoc,
  makeSearchDocsPacket,
} from "./fixtures";

describe("domainOf / faviconUrl", () => {
  it("extracts the host without a www prefix", () => {
    expect(domainOf("https://www.acme.com/a/b")).toBe("acme.com");
    expect(domainOf("http://docs.example.org")).toBe("docs.example.org");
  });

  it("returns null for empty / non-url input", () => {
    expect(domainOf(null)).toBeNull();
    expect(domainOf("")).toBeNull();
    expect(faviconUrl(null)).toBeNull();
  });

  it("builds a favicon url from the host", () => {
    expect(faviconUrl("https://www.acme.com")).toContain("acme.com");
  });
});

describe("selectSources", () => {
  it("splits cited (citation order) / more / files and dedupes", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeSearchDocsPacket([
        makeSearchDoc({ document_id: "d3" }), // uncited
        makeSearchDoc({ document_id: "d1" }),
        makeSearchDoc({ document_id: "d2" }),
        makeSearchDoc({
          document_id: "f1",
          file_id: "f1",
          link: null,
          source_type: "user_file",
        }),
      ]),
      makeCitationPacket(1, "d2"),
      makeCitationPacket(2, "d1"),
    ]);

    const selected = selectSources(state);
    expect(selected.cited.map((d) => d.document_id)).toEqual(["d2", "d1"]);
    expect(selected.more.map((d) => d.document_id)).toEqual(["d3"]);
    expect(selected.files.map((d) => d.document_id)).toEqual(["f1"]);
    expect(selected.count).toBe(4);
    expect(selected.hasSources).toBe(true);
    expect(selected.iconDocs.map((d) => d.document_id)).toEqual(["d2", "d1"]);
  });

  it("falls back to file docs for the icon stack when there are no web sources", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeSearchDocsPacket([
        makeSearchDoc({
          document_id: "f1",
          file_id: "f1",
          link: null,
          source_type: "user_file",
        }),
      ]),
      makeCitationPacket(1, "f1"),
    ]);

    const selected = selectSources(state);
    expect(selected.cited).toEqual([]);
    expect(selected.more).toEqual([]);
    expect(selected.files.map((d) => d.document_id)).toEqual(["f1"]);
    expect(selected.iconDocs.map((d) => d.document_id)).toEqual(["f1"]);
  });

  it("reports no sources for an empty state", () => {
    const selected = selectSources(createInitialState(1));
    expect(selected.hasSources).toBe(false);
    expect(selected.count).toBe(0);
  });

  it("hides sources when citations have no matching documents", () => {
    let state = createInitialState(1);
    state = processPackets(state, [makeCitationPacket(1, "missing-doc")]);
    const selected = selectSources(state);
    expect(selected.count).toBe(0);
    expect(selected.hasSources).toBe(false);
  });
});
