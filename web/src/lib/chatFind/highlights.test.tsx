import { render } from "@tests/setup/test-utils";
import { AnswerMarkdown } from "@/lib/answerText/components";
import {
  collectChatFindRanges,
  openDetailsAround,
} from "@/lib/chatFind/highlights";
import { answerFindSegments, findOccurrences } from "@/lib/chatFind/match";

const ANSWER =
  "> [!NOTE]\n> Mind the note.\n\n<details><summary>More note</summary>\n\nHidden note text.\n\n</details>";

function renderAnswer(): HTMLElement {
  const { container } = render(
    <div data-chat-find-text="answer:2">
      <AnswerMarkdown content={ANSWER} />
    </div>
  );
  return container;
}

test("the rendered answer and its searched text hold the same matches", () => {
  const root = renderAnswer();
  const ranges = collectChatFindRanges(root, "note").get("answer:2") ?? [];
  const counted = answerFindSegments(ANSWER).reduce(
    (count, segment) => count + findOccurrences(segment, "note").length,
    0
  );
  expect(ranges).toHaveLength(counted);
  expect(ranges.map((range) => range.startContainer.textContent)).toEqual([
    "Mind the note.",
    "More note",
    "Hidden note text.",
  ]);
});

test("a match in a closed details opens it; one in its summary does not", () => {
  const root = renderAnswer();
  const details = root.querySelector("details");
  const [, inSummary, inBody] =
    collectChatFindRanges(root, "note").get("answer:2") ?? [];
  if (!details || !inSummary || !inBody) throw new Error("missing matches");

  openDetailsAround(inSummary, root);
  expect(details.open).toBe(false);
  openDetailsAround(inBody, root);
  expect(details.open).toBe(true);
});
