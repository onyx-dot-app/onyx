import { ValidSources } from "../types";
import { OnyxDocument } from "@/lib/search/types";
import {
  countDocumentsBySource,
  documentMatchesAnySource,
  getDocumentSourceTypes,
  openDocument,
} from "./utils";

function makeDocument(overrides: Partial<OnyxDocument>): OnyxDocument {
  return {
    document_id: "doc-1",
    semantic_identifier: "doc.pdf",
    link: "",
    source_type: ValidSources.File,
    blurb: "",
    boost: 0,
    hidden: false,
    score: 0,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
    is_internet: false,
    ...overrides,
  };
}

describe("openDocument", () => {
  let windowOpen: jest.Mock;

  beforeEach(() => {
    windowOpen = jest.fn();
    (global as unknown as { window: { open: jest.Mock } }).window = {
      open: windowOpen,
    };
  });

  it("opens the link in a new tab when one is present", () => {
    const updatePresentingDocument = jest.fn();
    const document = makeDocument({
      link: "https://example.com/doc.pdf",
      source_type: ValidSources.Web,
    });

    openDocument(document, updatePresentingDocument);

    expect(windowOpen).toHaveBeenCalledWith(
      "https://example.com/doc.pdf",
      "_blank",
      "noopener,noreferrer"
    );
    expect(updatePresentingDocument).not.toHaveBeenCalled();
  });

  it("opens the in-app preview for connector File documents without a link", () => {
    const updatePresentingDocument = jest.fn();
    const document = makeDocument({
      link: "",
      source_type: ValidSources.File,
    });

    openDocument(document, updatePresentingDocument);

    expect(windowOpen).not.toHaveBeenCalled();
    expect(updatePresentingDocument).toHaveBeenCalledWith(document);
  });

  it("opens the in-app preview for user-uploaded UserFile documents without a link", () => {
    // Regression test: prior to the fix, "Uploaded Files" citations
    // (source_type=user_file, link=null) silently no-op'd on click because
    // openDocument only matched ValidSources.File.
    const updatePresentingDocument = jest.fn();
    const document = makeDocument({
      link: "",
      source_type: ValidSources.UserFile,
    });

    openDocument(document, updatePresentingDocument);

    expect(windowOpen).not.toHaveBeenCalled();
    expect(updatePresentingDocument).toHaveBeenCalledWith(document);
  });

  it("does nothing for non-file sources without a link", () => {
    const updatePresentingDocument = jest.fn();
    const document = makeDocument({
      link: "",
      source_type: ValidSources.Web,
    });

    openDocument(document, updatePresentingDocument);

    expect(windowOpen).not.toHaveBeenCalled();
    expect(updatePresentingDocument).not.toHaveBeenCalled();
  });

  it("tolerates a missing updatePresentingDocument callback", () => {
    const document = makeDocument({
      link: "",
      source_type: ValidSources.UserFile,
    });

    expect(() => openDocument(document)).not.toThrow();
    expect(windowOpen).not.toHaveBeenCalled();
  });
});

describe("getDocumentSourceTypes", () => {
  it("returns all unique source types when present", () => {
    const document = makeDocument({
      source_type: ValidSources.GoogleDrive,
      source_types: [
        ValidSources.GoogleDrive,
        ValidSources.Sharepoint,
        ValidSources.GoogleDrive,
      ],
    });

    expect(getDocumentSourceTypes(document)).toEqual([
      ValidSources.GoogleDrive,
      ValidSources.Sharepoint,
    ]);
  });

  it("falls back to the display source for old responses", () => {
    const document = makeDocument({
      source_type: ValidSources.Web,
      source_types: null,
    });

    expect(getDocumentSourceTypes(document)).toEqual([ValidSources.Web]);
  });

  it("matches any full source and falls back to the display source", () => {
    const multiSourceDocument = makeDocument({
      source_type: ValidSources.GoogleDrive,
      source_types: [ValidSources.GoogleDrive, ValidSources.Sharepoint],
    });
    const oldDocument = makeDocument({
      source_type: ValidSources.Web,
    });

    expect(
      documentMatchesAnySource(multiSourceDocument, [ValidSources.Sharepoint])
    ).toBe(true);
    expect(
      documentMatchesAnySource(multiSourceDocument, [ValidSources.Slack])
    ).toBe(false);
    expect(documentMatchesAnySource(oldDocument, [ValidSources.Web])).toBe(
      true
    );
  });

  it("counts a multi-source document in each source facet", () => {
    const counts = countDocumentsBySource([
      makeDocument({
        source_type: ValidSources.GoogleDrive,
        source_types: [ValidSources.GoogleDrive, ValidSources.Sharepoint],
      }),
      makeDocument({ source_type: ValidSources.GoogleDrive }),
    ]);

    expect(counts).toEqual(
      new Map([
        [ValidSources.GoogleDrive, 2],
        [ValidSources.Sharepoint, 1],
      ])
    );
  });
});
