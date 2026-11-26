import { render } from "@tests/setup/test-utils";
import { AnswerMarkdown } from "@/lib/answerText/components";
import {
  collectChatFindRanges,
  revealFoldedMatch,
} from "@/lib/chatFind/highlights";
import { answerFindSegments, findOccurrences } from "@/lib/chatFind/match";

const CALLOUT_AND_DETAILS =
  "> [!NOTE]\n> Mind the note.\n\n<details><summary>More note</summary>\n\nHidden note text.\n\n</details>";
const HTML_AND_FOOTNOTE =
  "A <b>note</b> here[^1].\n\n<div>note block</div>\n\n[^1]: The footnote note.";

function renderAnswer(content: string): HTMLElement {
  const { container } = render(
    <div data-chat-find-text="answer:2">
      <AnswerMarkdown content={content} />
    </div>
  );
  return container;
}

// The callout's "Note" title and the footnote are on the page, not searched.
test.each([
  [CALLOUT_AND_DETAILS, 3],
  [HTML_AND_FOOTNOTE, 2],
])(
  "the rendered answer and its searched text hold the same matches",
  (content, expected) => {
    const root = renderAnswer(content);
    const ranges = collectChatFindRanges(root, "note").get("answer:2") ?? [];
    const counted = answerFindSegments(content).reduce(
      (count, segment) => count + findOccurrences(segment, "note").length,
      0
    );
    expect(counted).toBe(expected);
    expect(ranges).toHaveLength(expected);
  }
);

test("a match in a closed details opens it; one in its summary does not", () => {
  const root = renderAnswer(CALLOUT_AND_DETAILS);
  const details = root.querySelector("details");
  const [, inSummary, inBody] =
    collectChatFindRanges(root, "note").get("answer:2") ?? [];
  if (!details || !inSummary || !inBody) throw new Error("missing matches");

  revealFoldedMatch(inSummary, root);
  expect(details.open).toBe(false);
  revealFoldedMatch(inBody, root);
  expect(details.open).toBe(true);
});

test("a match after a CRLF covers the matched text in the node", () => {
  const root = document.createElement("div");
  const scope = document.createElement("p");
  scope.setAttribute("data-chat-find-text", "row-1");
  scope.textContent = "a\r\nfoo";
  root.append(scope);

  const ranges = collectChatFindRanges(root, "foo").get("row-1") ?? [];
  expect(ranges.map((range) => range.toString())).toEqual(["foo"]);
});

test("a match never spans an inline image", () => {
  const content = "foo![alt](https://example.com/a.png)bar\n\nfoobar";
  const root = renderAnswer(content);
  const ranges = collectChatFindRanges(root, "foobar").get("answer:2") ?? [];
  const counted = answerFindSegments(content).reduce(
    (count, segment) => count + findOccurrences(segment, "foobar").length,
    0
  );
  expect(counted).toBe(1);
  expect(ranges).toHaveLength(1);
  const [range] = ranges;
  const paragraphs = root.querySelectorAll("p");
  expect(paragraphs).toHaveLength(2);
  expect(paragraphs[1]?.contains(range?.startContainer ?? null)).toBe(true);
});
