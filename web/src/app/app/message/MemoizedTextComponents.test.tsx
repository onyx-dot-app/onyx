import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { MemoizedAnchor } from "@/app/app/message/MemoizedTextComponents";
import { OnyxDocument } from "@/lib/search/types";
import { ValidSources } from "@/lib/connectors/types/source";

const FILE_ID = "3f2a9c1e-0000-4000-8000-000000000000";
const FILE_URL = `https://onyx.example.com/api/chat/file/${FILE_ID}`;

const citedDoc: OnyxDocument = {
  document_id: "doc_abc",
  semantic_identifier: "Quarterly Report",
  link: "https://docs.example.com/report",
  source_type: ValidSources.Web,
  blurb: "",
  boost: 0,
  hidden: false,
  score: 1,
  chunk_ind: 0,
  match_highlights: [],
  metadata: {},
  updated_at: null,
  is_internet: false,
};

describe("MemoizedAnchor", () => {
  test("bold-labeled chat file link opens the file preview", async () => {
    const updatePresentingDocument = jest.fn();
    render(
      <MemoizedAnchor
        href={FILE_URL}
        updatePresentingDocument={updatePresentingDocument}
      >
        <strong>Download the Word document</strong>
      </MemoizedAnchor>
    );

    const button = screen.getByRole("button", {
      name: "Download the Word document",
    });
    expect(button.querySelector("strong")).not.toBeNull();

    await userEvent.click(button);
    expect(updatePresentingDocument).toHaveBeenCalledWith({
      document_id: FILE_ID,
      semantic_identifier: "Download the Word document",
    });
  });

  test("bold-labeled external link renders as a link", () => {
    render(
      <MemoizedAnchor
        href="https://example.com/page"
        updatePresentingDocument={jest.fn()}
      >
        {[<strong key="b">Example</strong>, " page"]}
      </MemoizedAnchor>
    );

    const link = screen.getByRole("link", { name: "Example page" });
    expect(link).toHaveAttribute("href", "https://example.com/page");
  });

  test("plain citation label still renders as a citation", () => {
    render(
      <MemoizedAnchor
        href={citedDoc.link}
        updatePresentingDocument={jest.fn()}
        docs={[citedDoc]}
        citations={{ 1: citedDoc.document_id }}
      >
        [1]
      </MemoizedAnchor>
    );

    expect(screen.getByText("Quarterly Report")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
