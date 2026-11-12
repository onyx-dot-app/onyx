import { unified } from "unified";
import remarkParse from "remark-parse";
import { buildAnswerWithReferences } from "@/lib/chat/answerReferences";

const labels = {
  title: "Sources",
  unavailableSource: "Source details unavailable",
};
const citations = [{ citation_num: 1, document_id: "runbook" }];

test("preserves Markdown in the answer and escapes source labels and destinations", () => {
  const title = "Runbook [v2] <script> & *notes*\nNext line";
  const link = "https://example.com/guide_(v2)?a=1&copy=2#notes";
  const markdown = buildAnswerWithReferences(
    "```python\nprint('[1]')\n```",
    citations,
    [{ document_id: "runbook", semantic_identifier: title, link }],
    labels
  );
  const tree = unified().use(remarkParse).parse(markdown);
  expect(tree.children).toEqual([
    expect.objectContaining({
      type: "code",
      lang: "python",
      value: "print('[1]')",
    }),
    expect.objectContaining({ type: "heading", depth: 2 }),
    expect.objectContaining({
      type: "list",
      children: [
        expect.objectContaining({
          type: "listItem",
          children: [
            expect.objectContaining({
              type: "paragraph",
              children: [
                expect.objectContaining({
                  type: "link",
                  url: link,
                  children: [
                    expect.objectContaining({
                      type: "text",
                      value: title.replace("\n", " "),
                    }),
                  ],
                }),
              ],
            }),
          ],
        }),
      ],
    }),
  ]);
});

test.each([
  "javascript:alert(1)",
  "data:text/html,bad",
  "/api/chat/file/private",
  "#local",
  "",
])("keeps an unusable source link as plain text: %s", (link) => {
  expect(
    buildAnswerWithReferences(
      "Answer.",
      citations,
      [{ document_id: "runbook", semantic_identifier: "Runbook", link }],
      labels
    )
  ).toBe("Answer.\n\n## Sources\n\n- Runbook");
});

test("escapes characters that could end a Markdown destination", () => {
  expect(
    buildAnswerWithReferences(
      "Answer.",
      citations,
      [
        {
          document_id: "runbook",
          semantic_identifier: "Runbook",
          link: "https://example.com/a b<end>",
        },
      ],
      labels
    )
  ).toContain("(<https://example.com/a%20b%3Cend%3E>)");
});

test("uses the first document entry, matching the source panel", () => {
  expect(
    buildAnswerWithReferences(
      "Answer.",
      [...citations, ...citations],
      [
        { document_id: "runbook", semantic_identifier: "First", link: "" },
        { document_id: "runbook", semantic_identifier: "Second", link: "" },
      ],
      labels
    )
  ).toBe("Answer.\n\n## Sources\n\n- First");
});

test("does not label retrieved documents as citations when there are none", () => {
  expect(
    buildAnswerWithReferences(
      "Answer.",
      [],
      [
        {
          document_id: "runbook",
          semantic_identifier: "Runbook",
          link: "https://example.com",
        },
      ],
      labels
    )
  ).toBe("Answer.");
});
