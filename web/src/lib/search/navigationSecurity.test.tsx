import { openDocument } from "@/lib/search/utils";
import { ValidSources } from "@/lib/types";

it.each([
  "javascript:alert(1)",
  "java\nscript:alert(1)",
  "data:text/html,hello",
])("does not open executable document link %j", (link) => {
  const open = jest.spyOn(window, "open").mockImplementation(() => null);
  openDocument({
    document_id: "doc",
    semantic_identifier: "Doc",
    source_type: ValidSources.Web,
    blurb: "",
    boost: 0,
    hidden: false,
    score: 0,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
    is_internet: true,
    link,
  });
  expect(open).not.toHaveBeenCalled();
  openDocument({
    document_id: "doc",
    semantic_identifier: "Doc",
    source_type: ValidSources.Web,
    blurb: "",
    boost: 0,
    hidden: false,
    score: 0,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
    is_internet: true,
    link: "https://example.com/doc",
  });
  expect(open).toHaveBeenCalledWith(
    "https://example.com/doc",
    "_blank",
    "noopener,noreferrer"
  );
  open.mockRestore();
});
